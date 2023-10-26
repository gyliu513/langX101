import sys

def my_decorator(func):
    def wrapper(*args, **kwargs):
        print("Before calling the function")
        result = func(*args, **kwargs)
        print("After calling the function")
        return result
    return wrapper

def say_hello():
    print("Hello, world!")

# 使用装饰器装饰函数
decorated_say_hello = my_decorator(say_hello)

# 使用setattr将装饰后的函数赋值给原始函数的名称
setattr(sys.modules[__name__], "decorated_say_hello", decorated_say_hello)

decorated_say_hello()
