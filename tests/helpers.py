# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
Test helper objects
'''
import shlex
import subprocess
from copy import copy
from contextlib import contextmanager


class CmdStr(object):
    '''Build a command string from an iterable of format string tokens
    '''
    def __init__(self, program, template):
        self.prog = program
        self.template = list(template)  # list of tokens
        self._params = set()
        for i, item in enumerate(template):
            for _, name, fspec, conversion in item._formatter_parser():
                self._params.add(name)
                self.__dict__[name] = None
        self._init = True  # lock attribute creation

    def render(self):
        content = {}
        for key in self._params:
            value = self.__dict__[key]
            if value is not None:
                content[key] = value

        # filter acceptable tokens
        tokens = []
        for item in self.template:
            parser = item._formatter_parser()
            fields = set()
            # pytest.set_trace()
            for _, name, fspec, conversion in parser:
                if name:
                    fields.add(name)
            # print("fields '{}'".format(fields))
            # print("content '{}'".format(content))
            if all(field in content for field in fields):
                # only accept tokens for which we have all field values
                tokens.append(item)

        cmd = "{} {}".format(self.prog, ' '.join(tokens))
        return cmd.format(**content)

    def __setattr__(self, key, value):
        # immutable after instatiation
        if getattr(self, '_init', False) and key not in self.__dict__:
            raise AttributeError(key)
        object.__setattr__(self, key, value)
        # self.__dict__[key] = value

    def copy(self):
        return copy(self)


def get_runner(cmds):
    '''Return a context mng `runner` which will invoke all
    commands passed in `cmds` in order
    '''
    @contextmanager
    def runner(*args):
        runner.procs = {}
        runner.results = {}
        for ua in cmds:
            proc = subprocess.Popen(
                shlex.split(ua.render()),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            runner.procs[ua] = proc
        yield runner.procs
        # block for results
        for ua in cmds:
            # store (out, err)
            out, err = runner.procs[ua].communicate()
            runner.results[ua] = (out, err)

    runner.cmds = cmds
    return runner
