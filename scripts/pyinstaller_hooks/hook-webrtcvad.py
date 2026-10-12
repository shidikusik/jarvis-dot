"""The wheel distribution is webrtcvad-wheels; its import is webrtcvad."""
from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata("webrtcvad-wheels")
hiddenimports = ["_webrtcvad"]
