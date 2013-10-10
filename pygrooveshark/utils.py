import random
import string
import re

def random_hex():
    return ''.join(random.choice(string.hexdigits) for n in range(6))

def windows_filename(filename):
    return re.sub(r'[/\\:*?"<>|]', '', filename)
