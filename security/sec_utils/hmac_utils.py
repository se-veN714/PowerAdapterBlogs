# -*- coding: utf-8 -*-
# @File    : hmac_utils.py
# @Time    : 2025/7/28 16:56
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了hmac功能的类和函数。
"""

# here put the import lib
import secrets

from gmssl import sm3, func


def sm3_hmac(hmac_key: bytes, msg: bytes) -> str:
    """
        Calculate HMAC using SM3.
        :param hmac_key: secret key (recommended 32 bytes)
        :param msg: message to authenticate
        :return: hex string of HMAC-SM3
    """
    assert len(hmac_key) == 32, "Key must be 32 bytes (256 bits) long."

    OPAD = 0x5c
    IPAD = 0x36

    block_size = 64
    hmac_key = hmac_key.ljust(block_size, b'\x00')  # pad to block size

    o_key_pad = bytes([b ^ OPAD for b in hmac_key])
    i_key_pad = bytes([b ^ IPAD for b in hmac_key])

    inner = sm3.sm3_hash(func.bytes_to_list(i_key_pad + msg))
    outer = sm3.sm3_hash(func.bytes_to_list(o_key_pad + bytes.fromhex(inner)))

    return outer


def generate_key() -> bytes:
    return secrets.token_bytes(32)


if __name__ == "__main__":
    key = generate_key()
    print(key)