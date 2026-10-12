from jarvis.packs import recorded_reply


def test_exact_pack_reply_exists():
    path = recorded_reply("Запрос выполнен, сэр!")
    assert path and path.name == "done.wav" and path.is_file()


def test_new_text_is_not_silently_replaced_by_unrelated_recording():
    assert recorded_reply("Сейчас 12:34") is None
