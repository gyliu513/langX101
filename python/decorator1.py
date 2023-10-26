def simple_decorator(func):
    def wrapper(*args, **kwargs):
        """wrapper..."""
        print("Before calling the function")
        result = func(*args, **kwargs)
        print("After calling the function")
        return result
    return wrapper

@simple_decorator
def say_hello():
    """Say hello to the world."""
    print("Hello, world!")
    
print(say_hello.__name__)  # 输出: wrapper
print(say_hello.__doc__)   # 输出: None
say_hello()