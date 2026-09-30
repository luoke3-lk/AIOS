OUTPUT_FORMAT(elf32-i386)
OUTPUT_ARCH(i386)
ENTRY(_start)

SECTIONS
{
    . = 0x00010000;
    _kernel_start = .;

    .text ALIGN(16) :
    {
        KEEP(*(.text.start))
        *(.text .text.*)
    }

    .rodata ALIGN(16) :
    {
        *(.rodata .rodata.*)
    }

    .data ALIGN(16) :
    {
        *(.data .data.*)
    }

    .bss ALIGN(16) (NOLOAD) :
    {
        _bss_start = .;
        *(COMMON)
        *(.bss .bss.*)
        _bss_end = .;
    }

    _kernel_end = .;
    _pmm_bitmap = 0x00040000;
    _ai_arena = 0x00060000;
    _stack_top = 0x00090000;

    /DISCARD/ :
    {
        *(.comment .note .note.* .eh_frame .eh_frame_hdr)
    }
}
