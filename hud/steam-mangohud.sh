#!/bin/bash
# Abre a Steam com o MangoHud (overlay invisível) pré-carregado: todo jogo que a
# Steam iniciar herda, inclusive OpenGL nativo, sem opção de inicialização por jogo.
# A interface da Steam (steam/steamwebhelper) fica na lista de exclusões do MangoHud.
exec /usr/bin/mangohud /usr/bin/steam "$@"
