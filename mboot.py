#!/usr/bin/env python

# mboot.py - script to unpack and repack Intel boot.img for Android
# Copyright (c) 2014, Intel Corporation.
# Author: Jocelyn Falempe <jocelyn.falempe@intel.com>
#
# Modifications:
# Copyright (c) 2019, Chris Renshaw (osm0sis @ xda-developers)
#                     Shaka Huang (shakalaca @ xda-developers / ASUS ZenTalk)
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.

import os
import subprocess
from optparse import OptionParser
import struct
import re
import shutil

# call an external command
# optional parameter edir is the directory where it should be executed
def call(cmd, edir=''):
    if options.verbose:
        print '[', edir, '] Calling', cmd

    if edir:
        origdir = os.getcwd()
        os.chdir(os.path.abspath(edir))

    P = subprocess.Popen(args=cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, shell=True)

    if edir:
        os.chdir(origdir)

    stdout, stderr = P.communicate()
    if P.returncode:
        print cmd
        print "Failed " + stderr
        raise Exception('Error, stopping')
    return stdout

def write_file(fname, data, odir=True):
    if odir and options.dir:
        fname = os.path.join(options.dir, fname)
    print 'Write  ', fname
    out = open(fname, 'w')
    out.write(data)
    out.close()

def read_file(fname, odir=True):
    if odir and options.dir:
        fname = os.path.join(options.dir, fname)
    print 'Read   ', fname
    f = open(fname, 'r')
    data = f.read()
    f.close()
    return data

def read(fname, odir=True):
    if odir and options.dir:
        fname = os.path.join(options.dir, fname)
    try:
        f = open(fname, 'r')
        f.close()
        return fname
    except IOError:
        pass

def generate_checksum(hdr):
    checksum = 0
    hdr_calc = hdr[0:7] + struct.pack('B', 0) + hdr[8:56]
    for bit in hdr_calc:
        checksum ^= ord(bit)
    return checksum

# unpack the ramdisk to outdir
# caution, outdir is removed with rmtree() before unpacking
def unpack_ramdisk(fname, outdir):
    print 'Unpacking ramdisk to', outdir

    call('gunzip -f -k ' + fname, options.dir)
    fname = re.sub(r'\.gz$', '', fname)

    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    os.mkdir(outdir)
    call('cpio -i < ../' + fname, edir=outdir)

# return next few bytes from file f
def check_byte(f, size):
    origsize = size
    # try skipping first byte if \x00 to hopefully avoid false positives with isalnum()
    if size > 1:
        skip = f.read(1)
        if '\x00' in skip:
            size = size - 1
        else:
            f.seek(-1, os.SEEK_CUR)
    byte = f.read(size)
    f.seek(-origsize, os.SEEK_CUR)
    return byte

# Intel legacy format
def unpack_bootimg_intel(fname):
    f = open(fname, 'r')

    # header may rarely not exist on some products
    hdr = ''
    if not check_byte(f, 4).isalnum():
        hdr = f.read(512)
    print 'header size  ', len(hdr)

    # header may have 480, 728 or 1024 bytes of signature appended on some products
    sig = ''
    if not check_byte(f, 4).isalnum():
        sig = f.read(480)
        if not check_byte(f, 4).isalnum():
            sig += f.read(248)
            if not check_byte(f, 4).isalnum():
                sig += f.read(296)
    print 'sig size     ', len(sig)

    cmdline_block = f.read(4096)

    # bootstub is 4k, but can be 8k on some products
    bootstub = f.read(4096)
    if check_byte(f, 2).isalnum():
        bootstub += f.read(4096)
    print 'bootstub size', len(bootstub)

    kernelsize, ramdisksize = struct.unpack('II', cmdline_block[1024:1032])
    print 'kernel size  ', kernelsize
    print 'ramdisk size ', ramdisksize

    if kernelsize < 500000 or kernelsize > 15000000:
        print 'Error kernel size likely wrong'
        return

    if ramdisksize < 10000 or ramdisksize > 300000000:
        print 'Error ramdisk size likely wrong'
        return

    kernel = f.read(kernelsize)
    ramdisk = f.read(ramdisksize)

    cmdline = cmdline_block[0:1024]
    cmdline = cmdline.rstrip('\x00')
    parameters = cmdline_block[1032:1040]

    if hdr:
        write_file('hdr', hdr)
    if sig:
        write_file('sig', sig)
    write_file('cmdline.txt', cmdline)
    write_file('parameter', parameters)
    write_file('bootstub', bootstub)
    write_file('kernel', kernel)
    write_file('ramdisk.cpio.gz', ramdisk)

    f.close()

    if not options.original:
        unpack_ramdisk('ramdisk.cpio.gz', os.path.join(options.dir, 'extracted_ramdisk'))

def skip_pad(f, pgsz):
    npg = ((f.tell() / pgsz) + 1)
    f.seek(npg * pgsz)

def unpack_bootimg(fname):
    if options.dir == 'tmp_boot_unpack' and os.path.exists(options.dir):
        print 'Removing ', options.dir
        shutil.rmtree(options.dir)

    print 'Unpacking', fname, 'into', options.dir
    if options.dir:
        if not os.path.exists(options.dir):
            os.mkdir(options.dir)

    unpack_bootimg_intel(fname)

def pack_ramdisk(dname):
    dname = os.path.join(options.dir, dname)
    print 'Packing directory [', dname, '] => ramdisk.cpio.gz'
    call('find . | cpio -o -H newc > ../ramdisk.cpio', dname)
    call('gzip -f ramdisk.cpio', options.dir)

def pack_bootimg_intel(fname):
    if not options.original:
        pack_ramdisk('extracted_ramdisk')
    kernel = read_file('kernel')
    ramdisk = read_file('ramdisk.cpio.gz')

    cmdline = read_file('cmdline.txt')
    cmdline_block = cmdline + (1024 - len(cmdline)) * '\0'
    cmdline_block += struct.pack('II', len(kernel), len(ramdisk))
    cmdline_block += read_file('parameter')
    cmdline_block += '\0' * (4096 - len(cmdline_block))

    # add header if present
    hdr = ''
    if read('hdr'):
        hdr = read_file('hdr')

    # add signature back to header if present and add parameter padding magic for signed image
    if read('sig'):
        hdr += read_file('sig')
        cmdline_block = cmdline_block[0:1040] + '\xBD\x02\xBD\x02\xBD\x12\xBD\x12' + cmdline_block[1048:]
    # adjust header imgtype based on signature presence
    elif hdr:
        imgtype, = struct.unpack('I', hdr[52:56])
        hdr = hdr[0:52] + struct.pack('I', imgtype|0x01) + hdr[56:]

    data = cmdline_block
    data += read_file('bootstub')
    data += kernel
    data += ramdisk

    # pad to next full 512 byte sector
    topad = 512 - ((len(hdr) + len(data)) % 512)
    if topad < 512:
        data += '\xFF' * topad

    # update sector count and xor checksum in header
    if hdr:
        n_block = ((len(hdr) + len(data)) / 512 - 1)
        hdr = hdr[0:48] + struct.pack('I', n_block) + hdr[52:]
        checksum = generate_checksum(hdr)
        new_hdr = hdr[0:7] + struct.pack('B', checksum) + hdr[8:]
        data = new_hdr + data

    write_file(fname, data, odir=False)

def main():
    global options
    usage = 'Usage: %prog [options] boot.img\n\n' \
            '    unpack an Intel boot.img into separate files,\n' \
            '    OR pack a directory with kernel/ramdisk/bootstub into an Intel boot.img\n' \
            '    Default is to unpack to/pack from tmp_boot_unpack\n\n' \
            'Example:\n' \
            ' To unpack a boot.img image\n' \
            '    mboot.py -u boot.img\n' \
            ' modify tmp_boot_unpack/extracted_ramdisk/init.rc and run\n' \
            '    mboot.py boot-new.img'

    parser = OptionParser(usage, version='%prog 1.0')
    parser.add_option("-v", "--verbose",
                      action="store_true", dest="verbose")
    parser.add_option("-o", "--original",
                      action="store_true", dest="original", help='leave ramdisk packed/repack with original ramdisk')
    parser.add_option("-u", "--unpack",
                      action="store_true", dest="unpack", help='split boot image into kernel, ramdisk, bootstub ...')

    parser.add_option("-d", "--directory", dest="dir", default='tmp_boot_unpack',
                      help="extract boot.img to DIR, or create boot.img from DIR")

    (options, args) = parser.parse_args()


    if len(args) != 1:
        parser.error("takes exactly 1 argument")

    bootimg = args[0]

    if options.unpack:
        unpack_bootimg(bootimg)
        return

    if options.dir and not os.path.isdir(options.dir):
        print 'error ', options.dir, 'is not a valid directory'
        return

    pack_bootimg_intel(bootimg)

if __name__ == "__main__":
    main()
