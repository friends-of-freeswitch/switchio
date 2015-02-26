# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Manage pools of freeswitch slaves
"""
from itertools import cycle
from operator import add
from functools import partial
from utils import compose


class MultiEval(object):
    """Invoke arbitrary python expressions on a collection of objects
    """
    def __init__(self, slaves, delegator=cycle, accessor='.'):
        self._slaves = slaves
        self._cache = {}
        self.accessor = accessor
        self.delegator = delegator
        self.attrs(slaves)  # cache slaves iter
        for attr in filter(lambda n: '_' not in n[0], dir(slaves)):
            try:
                setattr(self.__class__, attr, getattr(self._slaves, attr))
            except AttributeError:
                pass

    @staticmethod
    def attrs(obj, _cache={}):
        """Cache of obj attributes since python has no built in for getting
        them all...
        """
        key = id(obj)
        try:
            return _cache[key]
        except KeyError:
            _cache[key] = {name: getattr(obj, name) for name in dir(obj)}
            return _cache[key]

    def __len__(self):
        return len(self._slaves)

    @property
    def nodes(self):
        return self._slaves

    def __iter__(self):
        """Deliver component tuples for each slave as per the delegator's
        servicing algorithm
        """
        return self.delegator(self._slaves)

    def evals(self, expr, **kwargs):
        """Evaluate expression on all slave sub-components
        (Warning: this is the slowest call)

        Parameters
        ----------
        name: str
            attr name of slave sub-component (i.e. `_slaves` is often a
            sequence of named tuples)
        expr: str
            python expression to evaluate on slave components
        """
        # Somehow faster then bottom one? - I assume this may not be the
        # case with py3. It's also weird how lists are faster then tuples...
        return [eval(expr, self.attrs(item), kwargs) for item in self._slaves]
        # return [res for res in self.iterevals(expr, **kwargs)]

    def iterevals(self, expr, **kwargs):
        # TODO: should consider passing code blocks that can be compiled
        # and exec-ed such that we can generate properties on the fly
        return self.partial(expr, **kwargs)()

    def reducer(self, func, expr, itertype='', **kwargs):
        """Reduces the iter retured by `evals(expr)` into a single value
        using the reducer `func`
        """
        # if callable(expr):
        #     # expr is a partial ready to call
        #     return compose(func, expr, **kwargs)
        # else:
        return compose(func, self.partial(expr, itertype=itertype),
                       **kwargs)

    def folder(self, func, expr, **kwargs):
        """Same as reducer but takes in a binary function
        """
        def fold(evals):
            return reduce(func, evals())
        return partial(fold, self.partial(expr, **kwargs))

    def partial(self, expr, **kwargs):
        """Return a partial which will eval bytcode compiled from `expr`
        """
        itertype = kwargs.pop('itertype', '')
        if not isinstance(itertype, str):
            # handle types as well
            itertype = itertype.__name__

        # namespace can contain kwargs which are refereced in `expr`
        ns = {'slaves': self._slaves}
        ns.update(kwargs)
        return partial(
            eval,
            compile("{}(item{}{} for item in slaves)"
                    .format(itertype, self.accessor, expr),
                    '<string>', 'eval'),
            ns)


def SlavePool(slaves):
    """A slave pool for controlling multiple servers with ease
    """
    # turns out to be slightly faster (x2) then the reducer call below
    def fast_count(self):
        return sum(i.listener.count_calls() for i in self._slaves)

    attrs = {
        'fast_count': fast_count,
    }
    # make a specialized instance
    sp = type('SlavePool', (MultiEval,), attrs)(slaves)

    # add other handy attrs
    for name in ('client', 'listener'):
        setattr(sp, 'iter_{}s'.format(name), sp.partial(name))
        setattr(sp, '{}s'.format(name), sp.evals(name))

    sp.hangup_causes = sp.evals('listener.hangup_causes')
    sp.causes = partial(reduce, add, sp.hangup_causes)

    # small reduction protocol for 'multi-actions'
    for attr in ('calls', 'jobs', 'sessions'):
        setattr(
            sp,
            'count_{}'.format(attr),
            sp.reducer(
                sum,
                'listener.count_{}()'.format(attr),
                itertype=list
            )
        )

    # figures it's slower then `causes` above...
    sp.aggr_causes = sp.folder(
        add,
        'listener.hangup_causes',
        itertype=list
    )
    return sp
