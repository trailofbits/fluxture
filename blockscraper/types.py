import itertools
from abc import ABCMeta
from collections import OrderedDict
from collections.abc import ValuesView
from enum import Enum
from typing import (
    Iterator, KeysView, OrderedDict as OrderedDictType, Tuple, Type, TypeVar, ValuesView as ValuesViewType
)
from typing_extensions import Protocol, runtime_checkable
import struct


P = TypeVar("P")


class ByteOrder(Enum):
    NATIVE = "@"
    LITTLE = "<"
    BIG = ">"
    NETWORK = "!"


@runtime_checkable
class Packable(Protocol):
    def pack(self, byte_order: ByteOrder = ByteOrder.NETWORK) -> bytes:
        ...

    @classmethod
    def unpack(cls: Type[P], data: bytes, byte_order: ByteOrder = ByteOrder.NETWORK) -> P:
        ...


class SizedIntegerMeta(ABCMeta):
    FORMAT: str
    BITS: int
    BYTES: int
    SIGNED: bool
    MAX_VALUE: int
    MIN_VALUE: int

    def __init__(cls, name, bases, clsdict):
        if name != "SizedInteger" and "FORMAT" not in clsdict:
            raise ValueError(f"{name} subclasses `SizedInteger` but does not define a `FORMAT` class member")
        super().__init__(name, bases, clsdict)
        if name != "SizedInteger":
            setattr(cls, "BYTES", struct.calcsize(f"{ByteOrder.NETWORK.value}{cls.FORMAT}"))
            setattr(cls, "BITS", cls.BYTES * 8)
            setattr(cls, "SIGNED", cls.FORMAT.islower())
            setattr(cls, "MAX_VALUE", 2**(cls.BITS - [0, 1][cls.SIGNED]) - 1)
            setattr(cls, "MIN_VALUE", [0, -2**(cls.BITS - 1)][cls.SIGNED])

    @property
    def c_type(cls) -> str:
        return f"{['u',''][cls.SIGNED]}int{cls.BITS}_t"


class SizedInteger(int, metaclass=SizedIntegerMeta):
    def __new__(cls: SizedIntegerMeta, value: int):
        retval: SizedInteger = int.__new__(cls, value)
        if not (cls.MIN_VALUE <= retval <= cls.MAX_VALUE):
            raise ValueError(f"{retval} is not in the range [{cls.MIN_VALUE}, {cls.MAX_VALUE}]")
        return retval

    def pack(self, byte_order: ByteOrder = ByteOrder.NETWORK) -> bytes:
        return struct.pack(f"{byte_order.value}{self.__class__.FORMAT}", self)

    @classmethod
    def unpack(cls, data: bytes, byte_order: ByteOrder = ByteOrder.NETWORK) -> "SizedInteger":
        return cls(struct.unpack(f"{byte_order.value}{cls.FORMAT}", data)[0])

    def __str__(self):
        return f"{self.__class__.c_type()}({int(self)})"


class Char(SizedInteger):
    FORMAT = 'b'


class UnsignedChar(SizedInteger):
    FORMAT = 'B'


class Short(SizedInteger):
    FORMAT = 'h'


class UnsignedShort(SizedInteger):
    FORMAT = 'H'


class Int(SizedInteger):
    FORMAT = 'i'


class UnsignedInt(SizedInteger):
    FORMAT = 'I'


class Long(SizedInteger):
    FORMAT = 'l'


class UnsignedLong(SizedInteger):
    FORMAT = 'L'


class LongLong(SizedInteger):
    FORMAT = 'q'


class UnsignedLongLong(SizedInteger):
    FORMAT = 'Q'


Int8 = Char
UInt8 = UnsignedChar
Int16 = Short
UInt16 = UnsignedShort
Int32 = Long
UInt32 = UnsignedLong
Int64 = LongLong
UInt64 = UnsignedLongLong


class StructMeta(ABCMeta):
    FIELDS: OrderedDictType[str, Type[Packable]]

    def __init__(cls, name, bases, clsdict):
        fields = OrderedDict()
        if "__annotations__" in clsdict:
            for field_name, field_type in clsdict["__annotations__"].items():
                if field_name == "FIELDS":
                    continue
                if isinstance(field_type, Packable):
                    fields[field_name] = field_type
                else:
                    raise TypeError(f"Field {field_name} of {name} must be a SizedInteger or Binary Message, "
                                    f"not {field_type}")
        super().__init__(name, bases, clsdict)
        setattr(cls, "FIELDS", fields)


class Struct(metaclass=StructMeta):
    def __init__(self, *args, **kwargs):
        unsatisfied_fields = [name for name in self.__class__.FIELDS.keys() if name not in kwargs]
        if len(args) > len(unsatisfied_fields):
            raise ValueError(f"Unexpected positional argument: {args[len(unsatisfied_fields)]}")
        elif len(args) < len(unsatisfied_fields):
            raise ValueError(f"Missing argument for {unsatisfied_fields[0]}")
        for name, value in itertools.chain(kwargs.items(), zip(unsatisfied_fields, args)):
            setattr(self, name, self.__class__.FIELDS[name](value))
        super().__init__()

    def pack(self, byte_order: ByteOrder = ByteOrder.NETWORK) -> bytes:
        # TODO: Combine the formats and use a single struct.pack instead
        return b"".join(getattr(self, field_name).pack(byte_order) for field_name in self.__class__.FIELDS.keys())

    @classmethod
    def unpack(cls: Type[P], data: bytes, byte_order: ByteOrder = ByteOrder.NETWORK) -> P:
        return cls(*struct.unpack(
            byte_order.value + "".join(field_type.FORMAT for field_type in cls.FIELDS.values()), data)
        )

    def __contains__(self, field_name: str):
        return field_name in self.__class__.FIELDS

    def __getitem__(self, field_name: str) -> Packable:
        if field_name not in self:
            raise KeyError(field_name)
        return getattr(self, field_name)

    def __len__(self) -> int:
        return len(self.__class__.FIELDS)

    def __iter__(self) -> Iterator[str]:
        return iter(self.__class__.FIELDS.keys())

    def items(self) -> Iterator[Tuple[str, Packable]]:
        for field_name in self:
            yield field_name, getattr(self, field_name)

    def keys(self) -> KeysView[str]:
        return self.__class__.FIELDS.keys()

    def values(self) -> ValuesViewType[Packable]:
        return ValuesView(self)

    def __eq__(self, other):
        return isinstance(other, Struct) and len(self) == len(other) and all(
            a == b for (_, a), (_, b) in zip(self.items(), other.items())
        )

    def __ne__(self, other):
        return not (self == other)

    def __str__(self):
        types = "".join(f"    {field_name} = {field_value!s};\n" for field_name, field_value in self.items())
        newline = "\n"
        return f"typedef struct {{{['', newline][len(types) > 0]}{types}}} {self.__class__.__name__}"
