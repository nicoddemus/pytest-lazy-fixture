# -*- coding: utf-8 -*-
import os
import sys
import types
from collections import defaultdict
import py
import pytest
from _pytest.fixtures import scopenum_function
from _pytest.python import Instance
from _pytest.unittest import TestCaseFunction


PY3 = sys.version_info[0] == 3
string_type = str if PY3 else basestring


def pytest_namespace():
    return {'lazy_fixture': lazy_fixture}


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    if isinstance(item, TestCaseFunction):
        return

    fixturenames = item.fixturenames
    argnames = item._fixtureinfo.argnames

    for fname in fixturenames:
        if fname not in item.funcargs and fname not in argnames:
            item.funcargs[fname] = item._request.getfixturevalue(fname)

    if hasattr(item, 'callspec'):
        for param, val in sorted_by_dependency(item.callspec.params):
            if is_lazy_fixture(val):
                item.callspec.params[param] = item._request.getfixturevalue(val.name)

    if isinstance(item.parent, Instance):
        def newinstance(self):
            return self.obj

        item.parent.newinstance = types.MethodType(
            newinstance, item.parent
        )


def pytest_runtest_call(item):
    if hasattr(item, 'funcargs'):
        for arg, val in item.funcargs.items():
            if is_lazy_fixture(val):
                item.funcargs[arg] = item._request.getfixturevalue(val.name)


@pytest.hookimpl(hookwrapper=True)
def pytest_generate_tests(metafunc):
    yield

    normalize_metafunc_calls(metafunc, 'funcargs')
    normalize_metafunc_calls(metafunc, 'params')


def normalize_metafunc_calls(metafunc, valtype):
    newcalls = []
    for callspec in metafunc._calls:
        calls = normalize_call(callspec, metafunc, valtype)
        newcalls.extend(calls)
    metafunc._calls = newcalls


def normalize_call(callspec, metafunc, valtype, used_keys=None):
    fm = metafunc.config.pluginmanager.get_plugin('funcmanage')
    config = metafunc.config

    used_keys = used_keys or set()
    valtype_keys = set(getattr(callspec, valtype).keys()) - used_keys

    newcalls = []
    for arg in valtype_keys:
        val = getattr(callspec, valtype)[arg]
        if is_lazy_fixture(val):
            fname = val.name
            nodeid = get_nodeid(metafunc.module, config.rootdir)
            fdef = fm.getfixturedefs(fname, nodeid)
            if fname not in callspec.params and fdef and fdef[-1].params:
                for i, param in enumerate(fdef[0].params):
                    newcallspec = callspec.copy(metafunc)
                    # TODO: for now it uses only function scope
                    # TODO: idlist
                    newcallspec.setmulti({fname: 'params'},
                                         (fname,), (param,),
                                         None, (), scopenum_function, i)
                    calls = normalize_call(newcallspec, metafunc, valtype, used_keys | set([arg]))
                    newcalls.extend(calls)
                return newcalls
        used_keys = used_keys | set([arg])
    return [callspec]


def sorted_by_dependency(params):
    free_fm = []
    non_free_fm = defaultdict(list)

    for key in params:
        val = params[key]

        if not is_lazy_fixture(val) or val.name not in params:
            free_fm.append(key)
        else:
            non_free_fm[val.name].append(key)

    non_free_fm_list = []
    for free_key in free_fm:
        non_free_fm_list.extend(
            _tree_to_list(non_free_fm, free_key)
        )

    return [(key, params[key]) for key in (free_fm + non_free_fm_list)]


def _tree_to_list(trees, leave):
    lst = []
    for l in trees[leave]:
        lst.append(l)
        lst.extend(
            _tree_to_list(trees, l)
        )
    return lst


def get_nodeid(module, rootdir):
    path = py.path.local(module.__file__)
    relpath = path.relto(rootdir)
    if os.sep != "/":
        relpath = relpath.replace(os.sep, "/")
    return relpath


def lazy_fixture(names):
    if isinstance(names, string_type):
        return LazyFixture(names)
    else:
        return [LazyFixture(name) for name in names]


def is_lazy_fixture(val):
    return isinstance(val, LazyFixture)


class LazyFixture(object):
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '<{} "{}">'.format(self.__class__.__name__, self.name)

    def __eq__(self, other):
        return self.name == other.name
