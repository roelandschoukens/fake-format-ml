try:
    # ideally, use regex. This supports Unicode regular expressions
    from regex import *
    has_regex = True
    
except:
    # shim to filter out our \p{...} patterns
    import re as _re
    from re import escape
    
    _RE_PZ = _re.compile(r'\\p\{Z[a-z]?\}')
    _RE_N_PZ = _re.compile(r'\\P\{Z[a-z]?\}')
    _RE_P = _re.compile(r'\\[pP]\{[A-Za-z]+\}')
    
    def _filter(exp):
        exp = _RE_PZ.sub(r'\\s', exp)
        exp = _RE_N_PZ.sub(r'\\S', exp)
        exp = _RE_P.sub('', exp)
        return exp
    
    def match(exp, str):
        return _re.match(_filter(exp), str)

    def sub(exp, repl, str):
        return _re.sub(_filter(exp), repl, str)

    def compile(exp):
        return _re.compile(_filter(exp))
        
    has_regex = False
