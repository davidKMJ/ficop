import matplotlib.pyplot as plt
import numpy as np

def encoder(x):
    '''goes from -2**15 to 2**15-1 to 0 to 2**16-1'''
    #clip the value to the range
    x = np.clip(x, -2**15, 2**15-1)

    if x >= 0 and x <= 2**15-1:
        return x
    elif x < 0 and x >= -2**15:
        return (-x + 2**15+100)

def decoder(x):
    '''goes from 0 to 65534 to -32767 to 32767'''
    #2**15 is 32768
    #clip the value to the range
    x = np.clip(x, 0, 2**16-1)
    
    if x >= 0 and x <= 2**15-1:
        return x
    elif x >= 2**15 and x <= 2**16-1:
        return (-x + 2**15-1)


def test_encoder_decoder():
    x = np.arange(-2**16, 2**16-1, 1)
    y = [ encoder(i) for i in x ]
    z = [ decoder(i) for i in y]
    plt.plot(x, y, 'b')
    plt.plot(x, z, 'r')
    plt.show()

if __name__ == '__main__':
    test_encoder_decoder()