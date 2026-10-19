#!/bin/bash
# Abre o TLauncher com o MangoHud (overlay invisível) pré-carregado: o Minecraft que ele
# iniciar herda o LD_PRELOAD e grava o FPS em ~/.cache/gamerhud/fps (log java_*).
# Minecraft é OpenGL, então só MANGOHUD=1 (camada Vulkan) não basta, e o GLFW dele pega o
# glXSwapBuffers com dlsym direto na libGLX.so.0: o libMangoHud_opengl.so sozinho nunca vê o
# frame. Por isso o shim (o mesmo do comando `mangohud`), que intercepta dlopen/dlsym; aqui
# não há overlay da Steam para travar com ele (ver steam-mangohud.sh). O próprio TLauncher
# também é java e desenha em OpenGL; o vigia e o HUD só aceitam o log java_* com o cliente
# do Minecraft aberto (o launcher se esconde quando o jogo começa).
MANGOHUD_LIB='/usr/$LIB/mangohud/libMangoHud_shim.so'

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
