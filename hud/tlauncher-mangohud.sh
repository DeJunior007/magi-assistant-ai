#!/bin/bash
# Abre o TLauncher com o MangoHud (overlay invisível) pré-carregado: o Minecraft que ele
# iniciar herda o LD_PRELOAD e grava o FPS em ~/.cache/gamerhud/fps (log java_*).
# Minecraft é OpenGL, então só MANGOHUD=1 (camada Vulkan) não basta. O próprio TLauncher
# também é java e desenha em OpenGL; o vigia e o HUD só aceitam o log java_* com o cliente
# do Minecraft aberto (o launcher se esconde quando o jogo começa).
MANGOHUD_LIB='/usr/$LIB/mangohud/libMangoHud_opengl.so'

preload=
IFS=: read -ra libs <<< "${LD_PRELOAD-}"
for lib in "${libs[@]}"; do
    case "$lib" in
        ''|*/mangohud/libMangoHud*) ;;
        *) preload="${preload:+$preload:}$lib" ;;
    esac
done

export MANGOHUD=1
export LD_PRELOAD="${preload:+$preload:}$MANGOHUD_LIB"
exec "$HOME/.local/share/TLauncher/tlauncher.sh" "$@"
