import config
from utils.deco import log


class stack(list):
    def push(self, obj):
        self.append(obj)
    def peek(self, i=-1):
        try: return self[i]
        except: return None


class Op:
    def __init__(self, type, function, priority):
        self.type = type
        self.func = function
        self.priority = priority
        self.sym = self.func.__name__

    def __call__(self, *args):
        return self.func(*args)

    def __repr__(self):
        return f"{self.type}({self.sym}, {self.priority})"
    
    def __str__(self):
        return self.sym


class Env(dict):
    def __init__(self, val=None, parent=None, name=None, binds=None):
        if val is not None:
            self.val = val
        self.parent = parent
        if not name:
            name = '(%s)' % hex(id(self))[-3:]
        self.name = name
        if binds:
            self.update(binds)
    
    def __getitem__(self, name):
        if name == 'this':
            return self
        if name in self:
            return super().__getitem__(name)
        if self.parent:
            return self.parent[name]
        raise KeyError('unbound name: ' + name)

    def dir(self):
        if self.parent or self.parent.name[0] in '_(':
            return self.name
        else:
            return self.parent.dir() + '.' + self.name

    def delete(self, name):
        try: self.pop(name)
        except: print('%s is unbound')

    def child(self, val=None, name=None, binds=None):
        env = Env(val, self, name, binds)
        return env

    def __repr__(self):
        return  '<env: %s>' % self.dir()
    
    def __str__(self):
        content = ', '.join(f'{k} = {v}' for k, v in self.items())
        return f'({content})'
    
    def __bool__(self):
        return True
    
    def all(self):
        d = {'(parent)': self.parent}
        env = self
        while env:
            for k in env:
                if k not in d:
                    d[k] = env[k]
            env = env.parent
        return d


class Attr:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '.'+self.name

    def getFrom(self, env):
        assert isinstance(env, Env), 'not an Env'
        try: return env[self.name]
        except: return getattr(env, self.name)


class Map:
    match = lambda val, form, parent: NotImplemented
    eval  = lambda tree, parent: NotImplemented

    def __init__(self, tree, env, at=None):
        _, form, body = tree
        body = Map.eval(body, None)  # simplify the body
        split_pars(form, env)
        self.form = form
        self.body = body
        self.parent = env
        self.at = at
        self.dir = self.parent.dir()
        self.__name__ = '(map)'
        self._str = remake_str(tree, env)
    
    def __call__(self, val):
        local = self.parent.child()
        Map.match(self.form, val, local)
        if self.at:
            at = Map.eval(self.at, local)
            assert isinstance(at, Env), "@ not applied to an Env"
            local = at.child(binds=local)
            local['super'] = at.parent
        if config.debug:
            signature = f'{self.dir}.{self.__name__}{list(val)}'
            log(signature)
            log.depth += 1
            result = Map.eval(self.body, local)
            log.depth -= 1
            log(signature, ' ==> ', result)
            return result
        else:
            return Map.eval(self.body, local)
    
    def __repr__(self):
        return '<map: %s.%s>' % (self.dir, self.__name__)
    
    def __str__(self):
        return self._str
    
    # def composed(self, func):
    #     "Enable arithmetic ops on Map."
    #     body = ['SEQ', func, self.body]
    #     return Map(self.form, body)


class Range:

    class Iter:
        def __init__(self, first, last, step):
            self.current = first
            self.last = last
            self.step = step

        def __next__(self):
            current = self.current
            if (self.step > 0 and current > self.last) or \
                (self.step < 0 and current < self.last):
                raise StopIteration
            self.current += self.step
            return current

    def __init__(self, first, last, second=None):
        self.first = first
        self.second = second
        self.last = last
        self.step = 1 if second is None else second - first
        if self.step == 0: raise ValueError('the step of this range is 0')

    def __repr__(self):
        items = [self.first, self.second, self.last]
        if self.second is None: items.pop(1)
        return '..'.join(map(str, items))
        
    def __iter__(self):
        return Range.Iter(self.first, self.last, self.step)

    def __eq__(self, other):
        if not isinstance(other, Range): return False
        return (self.first == other.first and self.second == other.second
                and self.last == other.last)
        
        
def remake_str(tree, env):
    "Reconstruct a readable string from the syntax tree."
    
    def rec(tr, in_seq=False):  # $sub: whether it is a sub-recursion
        if type(tr) is not list:
            return str(tr)
        
        def group(s): return '(%s)' if in_seq else s
        # if in an operation sequence, add a pair of parentheses
        
        tag = tr[0]
        if ':' in tag: tag, subtag = tag.split(':', 1)
        
        if tag in ('NAME', 'SYM', 'PAR'):
            return tr[1]
        elif tag == 'DELAY':
            tr = [subtag] + tr[1:]
            return rec(tr, in_seq)
        elif tag == 'FIELD':
            return ''.join(map(rec, tr[1:]))
        elif tag == 'ATTR':
            return '.' + tr[1]
        elif tag == 'SEQ':
            return ''.join(rec(t, True) for t in tr[1:])
        elif tag[-2:] == 'OP':
            op = tr[1]
            if type(op) is str: op = Map.eval(tr, None)
            return (' %s ' if op.priority < 4 else '%s') % str(tr[1])
        elif tag == 'NUM':
            return str(tr[1])
        elif tag == 'FORM':
            _, pars, optpars, extpar = tr
            pars = [rec(par) for par in pars]
            optpars = [f'{rec(optpar)}: {default}' for optpar, default in optpars]
            extpar = [extpar+'~'] if extpar else []
            return "[%s]" % ', '.join(pars + optpars + extpar)
        elif tag == 'IF_ELSE':
            return group("%s if %s else %s" % tuple(map(rec, tr[1:])))
        elif tag == 'PAR_LST':
            split_pars(tr, env)
            return rec(tr)
        elif tag[-3:] == 'LST':
            return '[%s]' % ', '.join(map(rec, tr[1:]))
        elif tag == 'MAP':
            _, form, exp = tr
            return group('%s => %s' % (rec(form), rec(exp)))
        elif tag == 'DICT':
            return '(%s)' % ', '.join(map(rec, tr[1:]))
        elif tag == 'BIND':
            if tr[-1][0] == 'DOC': tr = tr[1:]
            tup = tuple(rec(t) for t in tr[1:])
            if tr[2][0][:2] == 'AT':
                return '%s %s = %s' % tup
            else:
                return '%s = %s' % tup
        elif tag == 'MATCH':
            _, form, exp = tr[1]
            return group('%s::%s' % (rec(form), rec(exp)))
        elif tag == 'CLOSURE':
            _, local, exp = tr
            return '%s %s' % (rec(local), rec(exp))
        elif tag == 'FUNC':
            _, name, form = tr
            return '%s%s' % (rec(name), rec(form))
        elif tag == 'WHEN':
            cases = tr[1:]
            return 'when(%s)' % ', '.join(': '.join(map(rec, case[1:]))
                                          for case in cases)
        elif tag == 'AT':
            return '@' + rec(tr[1])
        elif 'PRINT' in tag:
            return ''
        elif tag == 'DOC':
            return ''
        else:
            return str(list(map(rec, tr)))
    return rec(tree)


def split_pars(form, env):
    "Split a FORM syntax tree into 3 parts: pars, opt-pars, ext-par."
    if form[0] == 'FORM':
        return
    pars, opt_pars = [], []
    ext_par = None
    lst = [form] if len(form) == 2 and \
        type(form[1]) is str else form[1:]
    for t in lst:
        if t[0] == 'PAR':
            pars.append(t[1])
        elif t[0] == 'PAR_LST':
            split_pars(t, env)
            pars.append(t)
        elif t[0] == 'OPTPAR':
            opt_pars.append([t[1], Map.eval(t[2], env)])
        else:
            ext_par = t[1]
    form[:] = ['FORM', pars, opt_pars, ext_par]



if __name__ == "__main__":
    # interact()
    import doctest
    doctest.testmod()
    
