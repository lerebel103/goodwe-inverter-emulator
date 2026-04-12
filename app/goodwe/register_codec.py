from __future__ import annotations

import struct


def put_u16(registers: dict[int, int], address: int, value: int) -> None:
    registers[address] = int(value) & 0xFFFF


def put_i16(registers: dict[int, int], address: int, value: int) -> None:
    registers[address] = int(value) & 0xFFFF


def put_u32(registers: dict[int, int], address: int, value: int) -> None:
    v = int(value) & 0xFFFFFFFF
    registers[address] = (v >> 16) & 0xFFFF
    registers[address + 1] = v & 0xFFFF


def put_i32(registers: dict[int, int], address: int, value: int) -> None:
    v = int(value)
    if v < 0:
        v = (1 << 32) + v
    put_u32(registers, address, v)


def put_u64(registers: dict[int, int], address: int, value: int) -> None:
    v = int(value) & 0xFFFFFFFFFFFFFFFF
    registers[address] = (v >> 48) & 0xFFFF
    registers[address + 1] = (v >> 32) & 0xFFFF
    registers[address + 2] = (v >> 16) & 0xFFFF
    registers[address + 3] = v & 0xFFFF


def put_f32(registers: dict[int, int], address: int, value: float) -> None:
    b = struct.pack(">f", float(value))
    registers[address] = (b[0] << 8) | b[1]
    registers[address + 1] = (b[2] << 8) | b[3]


def put_ascii(registers: dict[int, int], address: int, text: str, register_count: int) -> None:
    padded = (text or "").ljust(register_count * 2)[: register_count * 2]
    for idx in range(register_count):
        hi = ord(padded[idx * 2])
        lo = ord(padded[idx * 2 + 1])
        registers[address + idx] = ((hi & 0xFF) << 8) | (lo & 0xFF)
