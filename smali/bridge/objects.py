# This file is part of pysmali's Smali API
# Copyright (C) 2023 MatrixEditor

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
Standard Java wrapper classes that will be registered to a VM
once it was created.
"""

Object = {
    "toString()Ljava/lang/String;": str,
    "<init>()V": lambda x: x,
    "hashCode()I": id,
    "getClass()Ljava/lang/Class;": lambda x: x.smali_class
}

Class = {
    "getSimpleName()Ljava/lang/String;": lambda x: x.name
}


