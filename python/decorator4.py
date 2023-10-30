import functools

class SimpleClass:
    def __init__(self, value):
        self.value = value

    def display(self):
        print(f"Value: {self.value}")


def instrument_method(cls, method_name):
    method = getattr(cls, method_name)

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        print(f"Before calling {method.__name__}")
        result = method(*args, **kwargs)
        print(f"After calling {method.__name__}")
        return result

    setattr(cls, method_name, wrapper)


# Instrument the 'display' method of the SimpleClass
instrument_method(SimpleClass, 'display')

# Usage:

obj = SimpleClass(42)
obj.display()
