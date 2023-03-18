# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import struct

from smali import SmaliValue, Type
from smali.opcode import *
from smali.bridge.frame import Frame
from smali.bridge.errors import ExecutionError
from smali.bridge.lang import SmaliObject
from smali.bridge.objects import Object, Class

__all__ = [
    'Executor', 'OpcodeExecutor', 'executor', 'nop', 'return_void',
    'return_object', 'goto', 'invoke', 'int_to_long', 'int_to_int',
    'int_to_char', 'int_to_byte', 'int_to_float', 'sput_object',
    'sget_object', 'rem_int__lit8', 'rem_int', 'const', 'const_class',
    'move_result', 'move', 'move_exception', 'new_instance'
]

__executors__ = {}
"""Sepcial dict tat stores all opcodes with their executors"""

class Executor:

    opcode: str
    """The linked opcode"""

    action = None
    """Optional action if this class is not subclassed."""

    frame: Frame = None
    """The current execution frame"""

    args: tuple = None
    """THe current execution arguments"""

    kwargs: dict = None
    """The current execution"""

    def __init__(self, action, name=None,
                 map_to: list = None) -> None:
        self.opcode = name
        self.action = action
        self.frame = None
        if self.action:
            self.opcode = (str(action.__name__)
                .replace('__', '/')
                .replace('_', '-'))

        if not self.opcode:
            raise ValueError('Opcode name must be non-null!')
        __executors__[self.opcode] = self
        if map_to:
            for op_name in map_to:
                __executors__[op_name] = self

    def __call__(self, frame: Frame):
        self.frame = frame
        self.args = self.args or ()
        if self.action:
            self.action(self, *self.args)

    def __repr__(self) -> str:
        return f"<{self.opcode} at {id(self):#x}>"

    def __str__(self) -> str:
        return self.__repr__()

    def cast(self, value, classes):
        if not isinstance(value, classes):
            raise ExecutionError('ClassCastError',
                f"Could not cast '{type(value)}' to {classes}")

        return value

def OpcodeExecutor(map_to=[]):
    def wrapper(func):
        return Executor(func, map_to=map_to)
    return wrapper

def executor(name: str) -> Executor:
    if name not in __executors__:
        raise KeyError(f'Could not find executor for opcode: {name}')

    return __executors__[name]


@OpcodeExecutor()
def nop(self):
    pass

################################################################################
# RETURN
################################################################################

@OpcodeExecutor(map_to=[RETURN_VOID_BARRIER, RETURN_VOID_NO_BARRIER])
def return_void(self: Executor):
    self.frame.return_value = None
    self.frame.finished = True


@OpcodeExecutor(map_to=[RETURN, RETURN_WIDE])
def return_object(self: Executor, register: str):
    self.frame.return_value = self.frame[register]
    self.frame.finished = True

################################################################################
# GOTO
################################################################################

@OpcodeExecutor(map_to=[GOTO_16, GOTO_32])
def goto(self: Executor, label: str):
    if label not in self.frame.labels:
        raise ExecutionError("NoSuchLabelError", label)

    self.frame.label = label
    self.frame.pos = self.frame.labels[label]

################################################################################
# INVOKE
################################################################################

@OpcodeExecutor(map_to=[
    INVOKE_DIRECT, INVOKE_STATIC, INVOKE_VIRTUAL
])
def invoke(self: Executor, inv_type, args, owner, method):
    # TODO: add direct calls to int or str objects
    if inv_type in ('direct', 'virtual', 'static'):
        vm_class = None
        if owner == 'Ljava/lang/Class;':
            # If class methods should be invoked, just use the
            # previously moved class object
            vm_class = self.frame[args[0]]
            if method not in Class:
                raise ExecutionError('NoSuchMethodError', f"method '{method}' not defined!")

            self.frame.method_return = Class[method](vm_class)
            return

        if owner == 'Ljava/lang/Object;':
            if method not in Object:
                raise ExecutionError('NoSuchMethodError', f"method '{method}' not defined!")

            target = Object[method]
            self.frame.method_return = target(self.frame[args[0]])
            return


        values = [self.frame[register] for register in args]
        instance = None
        if inv_type != 'static':
            instance = values[0]
            super_cls = instance.smali_class.super_cls
            if super_cls == owner:
                vm_class = self.frame.vm.get_class(super_cls)
            # Remove the first argument
            values = values[1:]

        if not vm_class:
            vm_class = self.frame.vm.get_class(owner)

        target = vm_class.method(method)
        self.frame.method_return = self.frame.vm.call(target, instance, *values)

@OpcodeExecutor()
def throw(self: Executor, register: str):
    self.frame.error = ExecutionError('RuntimeError', self.frame[register])

################################################################################
# INT-2-OBJECT, LONG-2-OBJECT
################################################################################

@OpcodeExecutor()
def int_to_long(self: Executor, dest: str, src: str):
    self.frame[dest] = self.frame[src] & 0xFFFFFFFFFFFFFFFF


@OpcodeExecutor(map_to=[LONG_TO_INT])
def int_to_int(self: Executor, dest: str, src: str):
    self.frame[dest] = self.frame[src] & 0xFFFFFFFF


@OpcodeExecutor(map_to=[INT_TO_SHORT])
def int_to_char(self: Executor, dest: str, src: str):
    self.frame[dest] = self.frame[src] & 0xFFFF


@OpcodeExecutor()
def int_to_byte(self: Executor, dest: str, src: str):
    self.frame[dest],  = struct.unpack('>i', self.frame[src])


@OpcodeExecutor(map_to=[INT_TO_DOUBLE])
def int_to_float(self: Executor, dest: str, src: str):
    self.frame[dest] = float(self.frame[src])

################################################################################
# GET, PUT
################################################################################

@OpcodeExecutor(map_to=[
    SPUT, SPUT_BOOLEAN, SPUT_SHORT, SPUT_CHAR, SPUT_BYTE,
    SPUT_OBJECT_VOLATILE, SPUT_WIDE,SPUT_WIDE_VOLATILE
])
def sput_object(self: Executor, register: str, dest: str):
    # The destination string contains the owner class name, field name and
    # field type.
    value = self.frame[register]

    owner, name_type = dest.split('->')
    name, _ = name_type.split(':')

    cls = self.frame.vm.get_class(owner)
    field = cls.field(name)
    field.value = value


@OpcodeExecutor(map_to=[
    SGET, SGET_BOOLEAN, SGET_BYTE, SGET_OBJECT_VOLATILE, SGET_VOLATILE,
    SGET_WIDE, SGET_WIDE_VOLATILE, SGET_CHAR
])
def sget_object(self: Executor, register: str, dest: str):
    # The destination string contains the owner class name, field name and
    # field type.
    owner, name_type = dest.split('->')
    name, _ = name_type.split(':')

    cls = self.frame.vm.get_class(owner)
    field = cls.field(name)
    self.frame[register] = field.value


@OpcodeExecutor(map_to=[
    IGET_BOOLEAN, IGET_BYTE, IGET_CHAR, IGET_SHORT,
    IGET_VOLATILE, IGET_WIDE, IGET, IGET_OBJECT_VOLATILE
])
def iget_object(self: Executor, dest: str, src: str, info: str):
    smali_object = self.cast(self.frame[src], SmaliObject)
    _, field = info.split('->')
    field_name, _ = field.split(':')

    self.frame[dest] = smali_object[field_name]


@OpcodeExecutor(map_to=[
    IPUT, IPUT_BOOLEAN, IPUT_BYTE, IPUT_CHAR,
    IPUT_SHORT, IPUT_OBJECT_VOLATILE, IPUT_VOLATILE,
    IPUT_WIDE
])
def iput_object(self: Executor, src: str, obj: str, info: str):
    smali_object = self.cast(self.frame[obj], SmaliObject)
    _, field = info.split('->')
    field_name, _ = field.split(':')

    smali_object[field_name] = self.frame[src]

################################################################################
# CONST
################################################################################

@OpcodeExecutor(map_to=[
    CONST_STRING, CONST_STRING_JUMBO, CONST_16, CONST_4,
    CONST_WIDE, CONST_WIDE_HIGH16, CONST_WIDE_32
])
def const(self: Executor, register: str, value: str):
    self.frame[register] = SmaliValue(value)


@OpcodeExecutor(map_to=[CONST_CLASS])
def const_class(self: Executor, register: str, name: str):
    self.frame[register] = self.frame.vm.get_class(name)

################################################################################
# MOVE
################################################################################

@OpcodeExecutor(map_to=[MOVE_RESULT_OBJECT])
def move_result(self: Executor, register: str):
    self.frame[register] = self.frame.method_return


@OpcodeExecutor()
def move(self: Executor, dest: str, src: str):
    self.frame[dest] = self.frame[src]


@OpcodeExecutor()
def move_exception(self: Executor, dest: str):
    self.frame[dest] = self.frame.error

################################################################################
# NEW-INSTANCE
################################################################################

@OpcodeExecutor()
def new_instance(self: Executor, register: str, descriptor: str):
    # Filter out primitive values
    if descriptor in "ISBJ":
        self.frame[register] = 0
    elif descriptor in "FD":
        self.frame[register] = 0.0
    elif descriptor in ('Ljava/lang/String;', 'C', 'Ljava/lang/Character;'):
        self.frame[register] = ""
    elif descriptor in ("Ljava/lang/Integer;", "Ljava/lang/Byte;",
                        "Ljava/lang/Long", "Ljava/lang/Short;"):
        self.frame[register] = 0
    elif descriptor in ("Ljava/lang/Boolean", "Z"):
        self.frame[register] = False
    else:
        smali_class = self.frame.vm.get_class(descriptor)
        instance = SmaliObject(smali_class)
        instance.init()

        self.frame[register] = instance


@OpcodeExecutor()
def new_array(self: Executor, dest: str, count_register: str, descriptor: str):
    cls = Type(descriptor).class_name
    values = [None] * self.frame[count_register]
    if cls in "BSIJ": # number
        values = [0] * self.frame[count_register]

    elif cls in "FD": # floating point
        values = [0.0] * self.frame[count_register]

    self.frame[dest] = values

################################################################################
# SWITCH
################################################################################

@OpcodeExecutor()
def packed_switch(self: Executor, register: str, data: str):
    switch_value, cases = self.frame.switch_data[data]
    value = self.frame[register]

    # We must convert the switch_value into a SmaliValue object
    # as it is of type string and we need an integer
    idx = value - SmaliValue(switch_value)

    if idx < 0 or idx >= len(cases):
        # Default branch does nothing
        return

    # Call GOTO-instruction directly
    goto.action(self, cases[idx])


@OpcodeExecutor
def sparse_switch(self: Executor, register: str, label_name: str):
    branches = self.frame.switch_data[label_name]
    value = self.frame[register]

    # The iteration is needed as the branch values are strings
    for key, label in branches.items():
        if SmaliValue(key) == value:
            goto.action(self, label)
            break

################################################################################
# IF
################################################################################

@OpcodeExecutor()
def if_le(self: Executor, left: str, right: str, label: str):
    if self.frame[left] <= self.frame[right]:
        goto.action(self, label)


@OpcodeExecutor()
def if_ge(self: Executor, left: str, right: str, label: str):
    if self.frame[left] >= self.frame[right]:
        goto.action(self, label)


@OpcodeExecutor()
def if_gez(self: Executor, left: str, label: str):
    if self.frame[left] >= 0:
        goto.action(self, label)


@OpcodeExecutor()
def if_ltz(self: Executor, left: str, label: str):
    if self.frame[left] < 0:
        goto.action(self, label)


@OpcodeExecutor()
def if_gt(self: Executor, left: str, right: str, label: str):
    if self.frame[left] > self.frame[right]:
        goto.action(self, label)


@OpcodeExecutor()
def if_lt(self: Executor, left: str, right: str, label: str):
    if self.frame[left] < self.frame[right]:
        goto.action(self, label)


@OpcodeExecutor()
def if_gtz(self: Executor, left: str, label: str):
    if self.frame[left] > 0:
        goto.action(self, label)


@OpcodeExecutor()
def if_ne(self: Executor, left: str, right: str, label: str):
    if self.frame[left] != self.frame[right]:
        goto.action(self, label)


@OpcodeExecutor()
def if_lez(self: Executor, left: str, label: str):
    if self.frame[left] <= 0:
        goto.action(self, label)


@OpcodeExecutor()
def if_nez(self: Executor, left: str, label: str):
    if self.frame[left] != 0:
        goto.action(self, label)


@OpcodeExecutor()
def if_eqz(self: Executor, left: str, label: str):
    if self.frame[left] == 0:
        goto.action(self, label)

################################################################################
# ARRAY
################################################################################

@OpcodeExecutor()
def array_length(self: Executor, dest: str, array: str):
    self.frame[dest] = len(self.frame[array])


@OpcodeExecutor()
def fill_array_data(self: Executor, dest: str, label: str):
    self.frame[dest] = self.frame.array_data[label]


@OpcodeExecutor(map_to=[
    AGET_BOOLEAN, AGET_BYTE, AGET_CHAR,
    AGET_OBJECT, AGET_SHORT, AGET_WIDE
])
def aget(self: Executor, dest: str, array: str, index: str):
    idx_value = self.frame[index]
    array_data = self.frame[array]
    if idx_value < 0 or idx_value >= len(array):
        raise ExecutionError(
            'IndexOutOfBoundsError',
            f"Index {idx_value} is out of bounds for length {len(array_data)}")

    self.frame[dest] = array_data[idx_value]


@OpcodeExecutor(map_to=[
    APUT_BOOLEAN, APUT_BYTE, APUT_CHAR,
    APUT_OBJECT, APUT_SHORT, APUT_WIDE
])
def aput(self: Executor, src: str, array: str, index: str):
    idx_value = self.frame[index]
    array_data = self.frame[array]
    if idx_value < 0 or idx_value > len(array):
        raise ExecutionError(
            'IndexOutOfBoundsError',
            f"Index {idx_value} is out of bounds for length {len(array_data)}")

    if len(array) == idx_value:
        array_data.append(self.frame[src])
    else:
        array_data[idx_value] = self.frame[src]

################################################################################
# Int operations (2addr)
################################################################################

@OpcodeExecutor(map_to=[NEG_DOUBLE, NEG_FLOAT, NEG_LONG])
def neg_int(self: Executor, dest: str, src: str):
    self.frame[dest] = -self.frame[src]


@OpcodeExecutor(map_to=[OR_LONG_2ADDR])
def or_int__2addr(self: Executor, dest: str, src: str):
    self.frame[dest] |= self.frame[src]


@OpcodeExecutor(map_to=[AND_LONG_2ADDR])
def and_int__2addr(self: Executor, dest: str, src: str):
    self.frame[dest] &= self.frame[src]


@OpcodeExecutor(map_to=[SUB_DOUBLE_2ADDR, SUB_FLOAT_2ADDR, SUB_LONG_2ADDR])
def sub_int__2addr(self: Executor, dest: str, src: str):
    self.frame[dest] -= self.frame[src]


@OpcodeExecutor(map_to=[XOR_LONG_2ADDR])
def xor_int__2addr(self: Executor, dest: str, src: str):
    self.frame[dest] ^= self.frame[src]


@OpcodeExecutor(map_to=[ADD_DOUBLE_2ADDR, ADD_FLOAT_2ADDR, ADD_LONG_2ADDR])
def add_int__2addr(self: Executor, dest: str, src: str):
    self.frame[dest] += self.frame[src]


@OpcodeExecutor(map_to=[DIV_LONG_2ADDR])
def div_int__2addr(self: Executor, dest: str, src: str):
    self.frame[dest] //= self.frame[src]


@OpcodeExecutor(map_to=[DIV_DOUBLE_2ADDR])
def div_float__2addr(self: Executor, dest: str, src: str):
    self.frame[dest] /= self.frame[src]


@OpcodeExecutor(map_to=[SHL_LONG_2ADDR])
def shl_int__2addr(self: Executor, dest: str, src: str):
    self.frame[dest] <<= self.frame[src]


@OpcodeExecutor(map_to=[SHR_LONG_2ADDR, USHR_INT_2ADDR, USHR_LONG_2ADDR])
def shr_int__2addr(self: Executor, dest: str, src: str):
    self.frame[dest] >>= self.frame[src]


@OpcodeExecutor(map_to=[REM_DOUBLE_2ADDR, REM_FLOAT_2ADDR, REM_LONG_2ADDR])
def rem_int__2addr(self: Executor, dest: str, src: str):
    self.frame[dest] %= self.frame[src]


@OpcodeExecutor(map_to=[MUL_DOUBLE_2ADDR, MUL_FLOAT_2ADDR, MUL_LONG_2ADDR])
def mul_int__2addr(self: Executor, dest: str, src: str):
    self.frame[dest] *= self.frame[src]

################################################################################
# Int operations (lit8 and lit16)
# div, add, sub, rem, and, or, xor, shl, shr, rsub(lit8)
################################################################################

@OpcodeExecutor()
def div_int__lit8(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] // (SmaliValue(right) & 0xFF)


@OpcodeExecutor()
def div_int__lit16(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] // (SmaliValue(right) & 0xFFFF)


@OpcodeExecutor()
def add_int__lit8(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] + (SmaliValue(right) & 0xFF)


@OpcodeExecutor()
def add_int__lit16(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] + (SmaliValue(right) & 0xFFFF)


@OpcodeExecutor()
def sub_int__lit8(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] - (SmaliValue(right) & 0xFF)


@OpcodeExecutor()
def sub_int__lit16(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] - (SmaliValue(right) & 0xFFFF)


@OpcodeExecutor()
def mul_int__lit8(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] * (SmaliValue(right) & 0xFF)


@OpcodeExecutor()
def mul_int__lit16(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] * (SmaliValue(right) & 0xFFFF)


@OpcodeExecutor()
def rem_int__lit8(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] % (SmaliValue(right) & 0xFF)


@OpcodeExecutor()
def rem_int__lit16(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] % (SmaliValue(right) & 0xFFFF)


@OpcodeExecutor()
def and_int__lit8(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] & (SmaliValue(right) & 0xFF)


@OpcodeExecutor()
def and_int__lit16(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] & (SmaliValue(right) & 0xFFFF)


@OpcodeExecutor()
def or_int__lit8(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] | (SmaliValue(right) & 0xFF)


@OpcodeExecutor()
def or_int__lit16(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] | (SmaliValue(right) & 0xFFFF)


@OpcodeExecutor()
def xor_int__lit8(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] ^ (SmaliValue(right) & 0xFF)


@OpcodeExecutor()
def xor_int__lit16(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] ^ (SmaliValue(right) & 0xFFFF)


@OpcodeExecutor()
def shl_int__lit8(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] << (SmaliValue(right) & 0xFF)


@OpcodeExecutor()
def shl_int__lit16(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] << (SmaliValue(right) & 0xFFFF)


@OpcodeExecutor()
def shr_int__lit8(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] >> (SmaliValue(right) & 0xFF)


@OpcodeExecutor()
def shr_int__lit16(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] >> (SmaliValue(right) & 0xFFFF)


@OpcodeExecutor()
def rsub_int__lit8(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = (SmaliValue(right) & 0xFF) - self.frame[left]

################################################################################
# Int operations
################################################################################

@OpcodeExecutor()
def div_int(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] // self.frame[right]


@OpcodeExecutor(map_to=[DIV_DOUBLE])
def div_float(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] / self.frame[right]


@OpcodeExecutor(map_to=[ADD_DOUBLE, ADD_FLOAT, ADD_LONG])
def add_int(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] + self.frame[right]


@OpcodeExecutor(map_to=[SUB_DOUBLE, SUB_FLOAT, SUB_LONG])
def sub_int(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] - self.frame[right]


@OpcodeExecutor(map_to=[REM_DOUBLE, REM_FLOAT, REM_LONG])
def rem_int(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] % self.frame[right]


@OpcodeExecutor(map_to=[MUL_DOUBLE, MUL_FLOAT, MUL_LONG])
def mul_int(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] * self.frame[right]


@OpcodeExecutor(map_to=[OR_LONG])
def or_int(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] | self.frame[right]


@OpcodeExecutor(map_to=[AND_LONG])
def and_int(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] & self.frame[right]


@OpcodeExecutor(map_to=[XOR_LONG])
def xor_int(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] ^ self.frame[right]


@OpcodeExecutor(map_to=[SHL_LONG])
def shl_int(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] << self.frame[right]


@OpcodeExecutor(map_to=[SHR_LONG, USHR_LONG, USHR_INT])
def shr_int(self: Executor, dest: str, left: str, right: str):
    self.frame[dest] = self.frame[left] >> self.frame[right]
