import errno
from pathlib import Path
import pytest
from rubric_gen.submission_revision import artifacts

@pytest.mark.parametrize('code',[errno.ENOTEMPTY,errno.EBUSY])
def test_transient_cleanup_retries_only_owned_tree(tmp_path,monkeypatch,code):
    root=tmp_path/'owned';root.mkdir();(root/'file').write_text('temporary')
    retained=tmp_path/'durable';retained.write_text('saved judgment')
    actual=artifacts.shutil.rmtree;calls=[];sleeps=[]
    def remove(path):
        calls.append(path)
        if len(calls)==1:raise OSError(code,'transient NFS cleanup',str(path))
        actual(path)
    monkeypatch.setattr(artifacts.shutil,'rmtree',remove)
    monkeypatch.setattr(artifacts.time,'sleep',sleeps.append)
    artifacts._force_remove_directory(root)
    assert not root.exists() and retained.read_text()=='saved judgment'
    assert calls==[root,root] and sleeps==[0.25]

@pytest.mark.parametrize('code',[errno.EACCES,errno.EIO])
def test_other_cleanup_errors_are_not_suppressed(tmp_path,monkeypatch,code):
    root=tmp_path/'owned';root.mkdir();calls=[]
    def remove(path):calls.append(path);raise OSError(code,'persistent failure')
    monkeypatch.setattr(artifacts.shutil,'rmtree',remove)
    with pytest.raises(OSError) as error:artifacts._force_remove_directory(root)
    assert error.value.errno==code and calls==[root]

def test_persistent_nfs_failure_is_bounded(tmp_path,monkeypatch):
    root=tmp_path/'owned';root.mkdir();calls=[];sleeps=[]
    def remove(path):calls.append(path);raise OSError(errno.ENOTEMPTY,'persistent')
    monkeypatch.setattr(artifacts.shutil,'rmtree',remove)
    monkeypatch.setattr(artifacts.time,'sleep',sleeps.append)
    with pytest.raises(OSError):artifacts._force_remove_directory(root)
    assert len(calls)==7 and sum(sleeps)==15.75 and root.exists()
