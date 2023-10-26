import functools

def simple_decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        print("Before calling the function")
        result = func(*args, **kwargs)
        print("After calling the function")
        return result
    return wrapper

@simple_decorator
def say_hello():
    """Say hello to the world."""
    print("Hello, world!")

print(say_hello.__name__)  # 输出: say_hello
print(say_hello.__doc__)   # 输出: Say hello to the world.

say_hello()