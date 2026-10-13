"""``ayanami-voz``: TTS Kokoro em CPU (dono: Y3.5; spec §5.4, design §4.3).

- :mod:`ayanami.voz.motor`: protocolo :class:`~ayanami.voz.motor.Motor`, o motor Kokoro real
  (``kokoro_onnx`` só importado dentro dele) e :class:`~ayanami.voz.motor.Gerenciador` (carga
  preguiçosa na 1ª fala, descarga após ``[voz] descarregar_apos_s`` ocioso, relógio injetado).
- :mod:`ayanami.voz.servidor`: ``ayanami voz --port 8741`` (``POST /falar``, ``GET /saude``).
"""
