; AIOS v0.1 BIOS boot sector source for Keystone.
; tools/asm_boot.py assembles the BITS16/BITS32 regions separately, injects
; build-time constants, pads the MBR code area, and appends 0x55AA.

[BITS16]
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00
    xor dh, dh
    mov word ptr [0x0500], dx
    mov word ptr [0x0502], KERNEL_SECTORS
    mov dword ptr [0x0504], KERNEL_BYTES
    sti

    ; A20 method 1: BIOS service.
    mov ax, 0x2401
    int 0x15
    jc a20_fallback
    mov dword ptr [0x0508], 1
    jmp a20_done

a20_fallback:
    ; Method 2 (fast gate) and method 3 (8042) are both attempted. This is
    ; deliberately verification-free to stay within the MBR byte budget.
    in al, 0x92
    or al, 0x02
    and al, 0xFE
    out 0x92, al
    mov dword ptr [0x0508], 2
    call kbc_wait_in
    mov al, 0xD1
    out 0x64, al
    call kbc_wait_in
    mov al, 0xDF
    out 0x60, al

a20_done:
    ; E820 header and up to 32 packed 24-byte records.
    mov dword ptr [0x8000], 0x30323845
    mov word ptr [0x8004], 0
    mov word ptr [0x8006], 32
    mov dword ptr [0x8008], 0
    mov dword ptr [0x800C], 0
    mov di, 0x8010
    xor ebx, ebx
    xor bp, bp

e820_next:
    mov eax, 0xE820
    mov ecx, 24
    mov edx, 0x534D4150
    mov dword ptr [di + 20], 1
    int 0x15
    jc e820_done
    cmp eax, 0x534D4150
    jne e820_done
    inc bp
    add di, 24
    cmp bp, 32
    je e820_done
    test ebx, ebx
    jne e820_next

e820_done:
    mov word ptr [0x8004], bp

    ; Construct a Disk Address Packet outside the MBR and prefer EDD/LBA.
    mov word ptr [0x0600], 0x0010
    mov word ptr [0x0602], KERNEL_SECTORS
    mov word ptr [0x0604], 0x0000
    mov word ptr [0x0606], 0x1000
    mov dword ptr [0x0608], KERNEL_LBA
    mov dword ptr [0x060C], 0
    mov bx, 0x55AA
    mov ah, 0x41
    mov dl, byte ptr [0x0500]
    int 0x13
    jc chs_load
    cmp bx, 0xAA55
    jne chs_load
    mov si, 0x0600
    mov ah, 0x42
    mov dl, byte ptr [0x0500]
    int 0x13
    jc disk_hang
    mov dword ptr [0x050C], 1
    jmp enter_pm

chs_load:
    ; Geometry fallback for 1.44MB media: 18 sectors, 2 heads.
    mov dword ptr [0x050C], 2
    mov si, KERNEL_LBA
    mov di, KERNEL_SECTORS
    mov ax, 0x1000
    mov es, ax

chs_next:
    mov ax, si
    xor dx, dx
    mov bx, 18
    div bx
    inc dl
    mov byte ptr [0x0620], dl
    xor dx, dx
    mov bx, 2
    div bx
    mov ch, al
    mov dh, dl
    mov cl, byte ptr [0x0620]
    xor bx, bx
    mov ax, 0x0201
    mov dl, byte ptr [0x0500]
    int 0x13
    jc disk_hang
    mov ax, es
    add ax, 0x20
    mov es, ax
    inc si
    dec di
    jne chs_next

enter_pm:
    cli
    ; Flat null/code/data GDT built below the boot sector.
    mov dword ptr [0x0700], 0
    mov dword ptr [0x0704], 0
    mov dword ptr [0x0708], 0x0000FFFF
    mov dword ptr [0x070C], 0x00CF9A00
    mov dword ptr [0x0710], 0x0000FFFF
    mov dword ptr [0x0714], 0x00CF9200
    mov word ptr [0x0718], 23
    mov dword ptr [0x071A], 0x00000700
    lgdt [0x0718]
    mov eax, cr0
    or eax, 1
    mov cr0, eax
    push 0x0008
    push PM_ENTRY
    retf

disk_hang:
    cli
boot_hang:
    hlt
    jmp boot_hang

kbc_wait_in:
    in al, 0x64
    test al, 0x02
    jne kbc_wait_in
    ret

[BITS32]
pm_entry:
    mov ax, 0x0010
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    mov esp, 0x00090000
    mov eax, 0x00010000
    jmp eax
