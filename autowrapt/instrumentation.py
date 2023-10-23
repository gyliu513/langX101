import autowrapt

autowrapt.bootstrap.init()  # Manually initialize autowrapt

@autowrapt.wrap('mypackage.simple_module:greet')
def wrapper(wrapped, instance, args, kwargs):
    print(f"Function {wrapped} called with arguments: {args}")
    return wrapped(*args, **kwargs)
