#coding: UTF8
import os, errno, re, shutil

from mercurial import ui, hg, util

import win32lfn

win32lfn.uisetup(ui.ui())

cwd = os.getcwd()

# 299 chars, mixed slashes
name = "123456789\\" + 28 * "123456789/" + "123456789"

uncname = win32lfn.uncabspath(name)

convolutedpath = "C:\\d/d\\d/././.\\..\\\\//."

shortpath = "C:\\"

# This is not a unicode string, it's a byte string
utfpath = 30 * "123456789\\" + u"aאהרון".encode("windows-1255")

def testcanonization():
    expectedpath = "\\\\?\\" + cwd + 30 * "\\123456789"
    assert uncname == expectedpath

    canonpath = win32lfn.uncabspath(convolutedpath)
    expected = "\\\\?\\C:\\d\\d"
    assert canonpath == expected

    normpath = os.path.normpath(convolutedpath)
    expected = "C:\\d\\d"
    assert normpath == expected

    shortunc = win32lfn.uncabspath(shortpath)
    expected = "\\\\?\\C:\\"
    assert shortunc == expected

    assert os.path.dirname(shortunc) == shortunc

    head, tail = os.path.split(shortunc)
    expected = "\\\\?\\C:\\"
    assert head == expected, tail == ""

    # Tempting as it is, make sure we don't touch paths that were already UNC
    assert win32lfn.uncabspath("\\\\?\\" + convolutedpath) == \
           "\\\\?\\" + convolutedpath

def testbadchdir():
    thrown = False
    try:
        os.chdir("Blargh")
    except OSError, err:
        assert err.errno == errno.ENOENT
        thrown = True
    assert thrown

def testnul():
    result = os.open(os.devnull, os.O_RDWR)
    assert result == 3


def computetestpaths():
    parent = os.path.normpath(os.path.join(name, ".."))

    testpaths = [(parent, "123456789"), (cwd, name), (cwd, uncname), (cwd, utfpath)]

    # Verify "\\servername\share\repo" works, using \\localhost\c$
    # This only works if the test is being run from a local drive, not a
    # network share
    index = uncname.find(":")
    if index != -1:
        drive, tail = re.findall("\\\\?\\\(.):(.*)", uncname)[0]
        sharename = r"\\localhost\%s$%s" % (drive, tail)
        testpaths.append((cwd, sharename))
    else:
        print "Skipping \\localhost\c$ tests, cwd is not on a local drive"

    return testpaths

def cleanup(d):
    if not os.path.exists(d):
        return
    shutil.rmtree(d)

#for testpath in testpaths:
def testos(root, d):
    print "Running os tests for %s, %s" % (root, d)
    f1 = os.path.join(d, "f1")
    f2 = os.path.join(d, "f2")

    assert os.path.split(f1) == (d, "f1")
    assert os.path.dirname(f2) == d
    assert os.path.basename(f2) == "f2"

    # Make the root if it doesn't exist and chdir into it, to test chdir
    if not os.path.exists(root):
        os.makedirs(root)
    os.chdir(root)

    os.makedirs(d)

    assert os.path.exists(d)
    assert os.path.isdir(d)

    os.rmdir(d)
    assert not os.path.exists(d)

    # os.mkdir must raise EEXIST if the directory exists
    os.mkdir(d)
    thrown = False
    try:
        os.mkdir(d)
    except OSError, err:
        thrown = True
        assert err.errno == errno.EEXIST
    assert thrown

    f = open(f1, 'w')
    f.write("Test")
    f.close()

    f = open(f1, 'r')
    assert f.readline() == "Test"
    f.close()

    os.stat(f1)
    os.lstat(f1)
    os.chmod(f1, 660)
    assert os.path.isfile(f1)

    files = os.listdir(d)
    assert len(files) == 1
    assert os.path.basename(f1) in files

    os.rename(f1, f2)
    os.stat(f2)
    assert not os.path.exists(f1)

    fd = os.open(f1, os.O_CREAT | os.O_BINARY | os.O_RDWR)
    os.write(fd, "Test2")
    os.close(fd)

    os.remove(f1)
    os.unlink(f2)
    os.removedirs(d)
    assert not os.path.exists(os.path.join(cwd, "123456789"))

    os.chdir(cwd)

def testutil(root, d):
    from mercurial import util

    try:
        from mercurial import window
        
        posixfile = windows.posixfile
        listdir = windows.listdir
    except:
        from mercurial import osutil

        posixfile = osutil.posixfile
        listdir = osutil.listdir

    def _util_unlink(file):
        if hasattr(util, "unlinkpath"):
            util.unlinkpath(file)
        else:
            util.unlink(file)

    print "Running util tests for %s, %s" % (root, d)

    if not os.path.exists(root):
        util.makedirs(root)
    os.chdir(root)

    util.makedirs(d)
    assert os.path.exists(d)

    f1 = os.path.join(d, "f1")
    f2 = os.path.join(d, "f2")
    f3 = os.path.join(d, "f3")

    print "f1: %s, f2: %s, f3: %s" % (f1, f2, f3)

    f = util.posixfile(f1, 'w')
    f.write("Test")
    f.close()

    util.copyfile(f1, f2)

    f = posixfile(f3, 'w')
    f.write("Test")
    f.close()

    files = os.listdir(d)
    assert len(files) == 3
    assert os.path.basename(f1) in files and\
           os.path.basename(f2) in files and\
           os.path.basename(f3) in files

    files = listdir(d)
    # print "\nDir: %s\nFiles: %s" % (d, files)
    assert len(files) == 3
    j = 1
    for file in files:
        assert file[0] == "f" + str(j)
        j += 1

    util.copyfiles("123456789", "d123456789")

    os.remove(f1)
    os.unlink(f2)
    _util_unlink(f3)
    assert not os.path.exists("123456789")

    # All the files still there after the copy?
    os.rename("d123456789", "123456789")
    files = os.listdir(d)
    assert len(files) == 3
    assert os.path.basename(f1) in files and\
           os.path.basename(f2) in files and\
           os.path.basename(f3) in files

    os.remove(f1)
    os.unlink(f2)
    _util_unlink(f3)
    assert not os.path.exists("123456789")

def testclean():
    print 'Testing "hg lfn clean"'

    util.makedirs(uncname)
    p = os.path.join(uncname, "f")
    f = util.posixfile(p, 'w')
    f.write("Test")
    f.close()

    u = ui.ui()
    r = hg.repository(u, "123456789", create=1)

    win32lfn.cleanDir(u, r, force=True)
    assert not os.path.exists(p)
    cleanup("123456789")

def testinit():
    print 'Testing "hg init"'
    u = ui.ui()
    r = hg.repository(u, uncname, create=1)
    cleanup("123456789")

    os.mkdir("123456789")
    os.chdir("123456789")
    r = hg.repository(u, ".", create=1)
    os.chdir("..")
    cleanup("123456789")

if __name__ == "__main__":
    # If the tests get interrupted or fail, this will cleanup
    cleanup("123456789")
    cleanup("d123456789")
    testnul()
    testcanonization()
    testbadchdir()
    testinit()
    for test in computetestpaths():
        testos(*test)
        testutil(*test)
    testclean()
