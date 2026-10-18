import tasklib


def test_add_and_find():
    tasklib.reset()
    task = tasklib.add("write docs")
    assert task["id"] == 1
    assert tasklib.find(1)["title"] == "write docs"
    assert tasklib.find(99) is None


def test_complete_marks_done():
    tasklib.reset()
    tasklib.add("ship it")
    tasklib.complete(1)
    assert tasklib.find(1)["done"] is True


if __name__ == "__main__":
    test_add_and_find()
    print("ok add_and_find")
    test_complete_marks_done()
    print("ok complete_marks_done")
    print("ALL OK")
