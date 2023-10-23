# print_instrumentation.py

import autowrapt

@autowrapt.wrap('builtins', 'print')
def custom_print(wrapped, instance, args, kwargs):
    new_args = ('[Instrumented]',) + args
    return wrapped(*new_args, **kwargs)
