from app.core import trainer


def _make_worker(monkeypatch):
    model = object()
    worker = trainer.TrainerWorker(
        model,
        trainer.TrainingConfig(epochs=1, batch_size=4, image_w=4, image_h=4,
                               val_split=0.25, num_workers=0, checkpoint_every=1),
        num_classes=2,
    )
    return worker


def test_non_oom_runtime_error_includes_batch_size_tip(monkeypatch):
    worker = _make_worker(monkeypatch)
    monkeypatch.setattr(worker, "_train", lambda: (_ for _ in ()).throw(RuntimeError("shape mismatch")))

    messages = []
    worker.training_error.connect(messages.append)
    worker.run()

    assert len(messages) == 1
    assert "shape mismatch" in messages[0]
    assert "Batch Size" in messages[0]
    assert "4" in messages[0]


def test_generic_exception_includes_batch_size_tip(monkeypatch):
    worker = _make_worker(monkeypatch)
    monkeypatch.setattr(worker, "_train", lambda: (_ for _ in ()).throw(ValueError("bad config")))

    messages = []
    worker.training_error.connect(messages.append)
    worker.run()

    assert len(messages) == 1
    assert "bad config" in messages[0]
    assert "Batch Size" in messages[0]


def test_oom_error_still_uses_dedicated_oom_help(monkeypatch):
    worker = _make_worker(monkeypatch)
    monkeypatch.setattr(worker, "_train", lambda: (_ for _ in ()).throw(RuntimeError("CUDA out of memory")))

    messages = []
    worker.training_error.connect(messages.append)
    worker.run()

    assert len(messages) == 1
    assert "GPU 메모리가 부족합니다" in messages[0]
    assert "Batch Size" in messages[0]
