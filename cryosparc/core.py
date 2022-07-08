from enum import Enum
from typing import Dict, List, Mapping, Optional, Tuple, Type, Union, overload
import numpy as n
import numpy.typing as nt

from .dtype import DType, Field, Shape
from .. import cryosparc_dataset


class DsetType(int, Enum):
    """
    Mirror of equivalent C-datatype enumeration
    """

    T_F32 = 1
    T_F64 = 2
    T_C32 = 3
    T_C64 = 4
    T_I8 = 5
    T_I16 = 6
    T_I32 = 7
    T_I64 = 8
    T_U8 = 9
    T_U16 = 10
    T_U32 = 11
    T_U64 = 12
    T_STR = 13


MAX_UINT64 = 0xFFFF_FFFF_FFFF_FFFF

DSET_TO_TYPE_MAP: Dict[DsetType, Type] = {
    DsetType.T_F32: n.float32,
    DsetType.T_F64: n.float64,
    DsetType.T_C32: n.complex64,
    DsetType.T_C64: n.complex128,
    DsetType.T_I8: n.int8,
    DsetType.T_I16: n.int16,
    DsetType.T_I32: n.int32,
    DsetType.T_I64: n.int64,
    DsetType.T_U8: n.uint8,
    DsetType.T_U16: n.uint16,
    DsetType.T_U32: n.uint32,
    DsetType.T_U64: n.uint64,
    DsetType.T_STR: n.object0,
}

TYPE_TO_DSET_MAP = {
    **{v: k for k, v in DSET_TO_TYPE_MAP.items()},
    **{
        float: DsetType.T_F64,
        complex: DsetType.T_C64,
        int: DsetType.T_I64,
        str: DsetType.T_STR,
        object: DsetType.T_STR,
    },
}


Int = Union[int, n.int8, n.int16, n.int32, n.int64]
Uint = Union[n.uint8, n.uint16, n.uint32, n.uint64]
Float = Union[float, n.float32, n.float64]
Complex = Union[complex, n.complex64, n.complex128]
Scalar = Union[Int, Uint, Float, Complex, n.object0]


def dtype_to_int(
    dt: nt.DTypeLike,
) -> Union[DsetType, Tuple[DsetType, nt.NDArray[n.uint8]]]:
    dt = n.dtype(dt)
    if dt.shape:
        assert dt.base in TYPE_TO_DSET_MAP, f"Unsupported column data type {dt.base}"
        return TYPE_TO_DSET_MAP[dt.base], n.array(dt.shape, dtype=n.uint8)
    else:
        assert dt in TYPE_TO_DSET_MAP, f"Unsupported column data type {dt.base}"
        return TYPE_TO_DSET_MAP[dt]


def generate_uids(num: int = 0):
    """
    Generate the given number of random 64-bit unsigned uids
    """
    return n.random.randint(0, MAX_UINT64, size=(num,), dtype=n.uint64)


class Data(Mapping[str, DType]):
    """
    Accessor and memory management class for native dataset memory. Can be used
    as a mapping where values are field type descriptors.
    """

    handle: int

    def __init__(self, copy_handle: int = 0) -> None:
        """
        Allocate new memory for a dataset
        """
        if copy_handle > 0:
            self.handle = cryosparc_dataset.dset_copy(copy_handle)
        else:
            self.handle = cryosparc_dataset.dset_new()

    def __del__(self):
        """
        When garbage-collected, removes memory for the given dataset
        """
        print(f"DATASET GARBAGE COLLECT FOR HANDLE {self.handle}")
        cryosparc_dataset.dset_del(self.handle)
        self.handle = 0

    def __len__(self) -> int:
        return self.ncol()

    def __getitem__(self, k: str) -> DType:
        t = self.type(k)
        if t == 0:
            raise KeyError(f"Unknown dset field {t}")
        assert t in DSET_TO_TYPE_MAP, f"Unknown dset field type {t}"
        dst = DsetType(t)
        dt = n.dtype(DSET_TO_TYPE_MAP[dst])
        shape = self.getshape(k)
        return (dt.str, shape) if shape else dt.str

    def __contains__(self, field: str):
        return self.type(field) > 0

    def __iter__(self):
        for i in range(self.ncol()):
            yield self.key(i)

    def __copy__(self):
        return Data(copy_handle=self.handle)

    def __deepcopy__(self):
        return self.__copy__()

    def totalsz(self) -> int:
        return cryosparc_dataset.dset_totalsz(self.handle)

    def copy(self) -> "Data":
        return self.__copy__()

    def ncol(self) -> int:
        return cryosparc_dataset.dset_ncol(self.handle)

    def nrow(self) -> int:
        return cryosparc_dataset.dset_nrow(self.handle)

    def key(self, index: int) -> str:
        return cryosparc_dataset.dset_key(self.handle, index)

    def type(self, field: str) -> int:
        return cryosparc_dataset.dset_type(field)

    def getptr(self, field: str) -> int:
        return cryosparc_dataset.dset_getptr(self.handle, field)

    def getshape(self, field: str) -> Shape:
        val: int = cryosparc_dataset.dset_getshp(self.handle)
        shape = (val & 0xFF, (val >> 8) & 0xFF, (val >> 16) & 0xFF)
        return tuple(s for s in shape if s != 0)

    def getstr(self, field: str, index: int) -> str:
        # TODO: See how bad the memory usage is due to having to create a new
        # string instance each time. Might be good to maintain a string cache
        # for each string column
        return cryosparc_dataset.dset_getstr(self.handle, field, index)

    def addrows(self, num) -> bool:
        return cryosparc_dataset.dset_addrows(self.handle, num) != 0

    @overload
    def addcol(self, field: Field) -> bool:
        ...

    @overload
    def addcol(self, field: str, dtype: nt.DTypeLike) -> bool:
        ...

    def addcol(self, field: Union[str, Field], dtype: Optional[nt.DTypeLike] = None) -> bool:
        if isinstance(field, tuple):
            field, *dt = field
            dt = n.dtype(dt[0]) if len(dt) == 1 else n.dtype(tuple(dt))
        else:
            dt = n.dtype(dtype)

        existing_type = self.type(field)
        assert existing_type == 0, f"Field {field} already defined in dataset"
        if dt.shape:
            assert dt.base in TYPE_TO_DSET_MAP, f"Unsupported column data type {dt.base}"
            return self.addcol_array(field, TYPE_TO_DSET_MAP[dt.base], dt.shape)
        else:
            assert dt in TYPE_TO_DSET_MAP, f"Unsupported column data type {dt}"
            return self.addcol_scalar(field, TYPE_TO_DSET_MAP[dt])

    def addcol_scalar(self, field: str, dtype: DsetType) -> bool:
        return cryosparc_dataset.dset_addcol_scalar(self.handle, field, dtype) != 0

    def addcol_array(self, field: str, dtype: DsetType, shape: Shape) -> bool:
        s = n.array(shape, dtype=n.uint8)
        return cryosparc_dataset.dset_addcol_array(self.handle, field, dtype, s) != 0

    def defrag(self) -> bool:
        return cryosparc_dataset.dset_defrag(self.handle) != 0
