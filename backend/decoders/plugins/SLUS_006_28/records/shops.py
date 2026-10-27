"""The shops' stock — g_ShopStockRows (0x800A8468), 0x28 rows of six item
numbers (ShopStockRow, shop.h), a table in the EXE's data that nothing
writes.

A script opens a shop with command 0x2E: ScriptCommandShopRun (0x8005E384)
hands the byte after its command word, the shop's number, to ShopRun
(0x80050694):

    if ((n & 0xFF) != 0 && (n & 0xFF) != 8) {
        g_ShopStockRow (0x800B8DC9) = n - 1;
        ShopOpen (0x800506EC)(); ShopStepsRun (0x800516CC)(); ShopClose (0x800512C4)();
    }

and ShopListSet (0x80051768) copies row ShopStockGet (0x8001BF1C)(g_ShopStockRow)
into the list, an item number a place, 0 an empty one. ShopStockGet
answers row n for n below 0x28 and the last row for 0x28 and up, so shop n
is row n - 1: shops 1 to 40. Shop 8 never opens; its row is six zeros.

Two rules of the code sit beside the table:

  * shop 0x22 takes no money: ShopItemDisp (0x80052C0C) never marks an
    item too dear, ShopDealRun (0x80053194) takes nothing off and
    ShopItemTextDisp (0x80053B18) shows the price as 0 (`FREE`);
  * while any of the party carries item 0xB5, ShopListSet clears it from
    the list (`HIDDEN_WHILE_CARRIED`).

The prices are the item table's (records.items, +0 and +2).

docs/spec/code/subsystems/menu-ui.md §"The shop".
"""

from __future__ import annotations

from dataclasses import dataclass

from .programs import address

BASE_ADDR = 0x800A8468          # g_ShopStockRows
EXE_BASE = 0x80011000           # where the EXE's header loads its image
STRIDE = 6                      # ShopStockRow: six item numbers
COUNT = 0x28                    # ShopStockGet: rows 0..0x27
FIRST, LAST = 1, COUNT          # shop n is row n - 1
#: ShopRun (0x80050694) opens nothing for these numbers (nor for 0).
CLOSED = (8,)
#: g_ShopStockRow + 1 == 0x22: the shop that takes no money.
FREE = 0x22
#: ShopListSet (0x80051768) clears this item while the party carries one.
HIDDEN_WHILE_CARRIED = 0xB5


@dataclass(frozen=True)
class Shop:
    number: int                 # ShopRun's argument: the row + 1
    places: tuple[int, ...]     # the six item numbers, 0 = an empty place

    @property
    def items(self) -> tuple[int, ...]:
        """The items it sells, in the list's order."""
        return tuple(i for i in self.places if i)

    @property
    def opens(self) -> bool:
        return self.number not in CLOSED

    @property
    def free(self) -> bool:
        return self.number == FREE


def read_from_exe(image: bytes) -> list[Shop]:
    """Every row, shop 1 to 40, out of the EXE code image (code.bin)."""
    base = address(image, "g_ShopStockRows", BASE_ADDR)
    off = base - EXE_BASE
    need = off + COUNT * STRIDE
    if off < 0 or len(image) < need:
        raise ValueError(f"image of {len(image):#x} bytes does not cover {base:#x}"
                         f" .. +{COUNT * STRIDE:#x} (need {need:#x})")
    return [Shop(FIRST + i, tuple(image[off + i * STRIDE:off + (i + 1) * STRIDE]))
            for i in range(COUNT)]
