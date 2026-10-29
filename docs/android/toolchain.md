# Toolchain Android no PC (condessa-celular, A0.1)

Tudo no diretório do usuário: nada com `sudo`, nada instalado em `/opt` ou `/usr`.
Conferido em 2026-10-28.

## Estado

| Peça | Onde | Versão |
| --- | --- | --- |
| SDK | `~/Android/Sdk` | — |
| Command-line tools | `~/Android/Sdk/cmdline-tools/latest` | 22.0 (`commandlinetools-linux-15859902_latest.zip`) |
| Plataforma | `platforms;android-36` (`compileSdk 36`) | rev 2 |
| Plataforma (já existia) | `platforms;android-36.1` | rev 1 |
| Build-tools | `build-tools;36.0.0` (padrão do AGP 9.0) | 36.0.0 |
| Build-tools (já existiam) | `build-tools;36.1.0`, `build-tools;37.0.0` | — |
| Platform-tools / emulador (já existiam) | `platform-tools`, `emulator` | 37.0.0 / 36.6.11 |
| JDK 21 | `/opt/android-studio/jbr` (JBR do Android Studio, só leitura) | 21.0.10 |

**JDK 21:** `/usr/lib/jvm/java-21-openjdk` existe mas está vazio (só sobrou `man/`; o pacote
`java-21-openjdk` não está instalado, `rpm -qa` só mostra o 25). Enquanto o Pedro não reinstalar o
JDK 21 do sistema, o Gradle roda com o JBR 21 que vem no Android Studio. O `java` padrão do sistema é
o 25 e não serve ao AGP/Kotlin desta spec (DSC2: JDK de build 21; o CI usa Temurin 21).

## Variáveis

```sh
export ANDROID_HOME="$HOME/Android/Sdk"
export JAVA_HOME=/opt/android-studio/jbr          # ou /usr/lib/jvm/java-21-openjdk, se reinstalado
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"
```

`android/local.properties` (fora do git, ver `.gitignore`):

```properties
sdk.dir=/home/pedrojr/Android/Sdk
```

Build (a partir da A0.2):

```sh
cd android && JAVA_HOME=/opt/android-studio/jbr ./gradlew --offline -q :app:testDebugUnitTest
```

## Comandos que rodaram

```sh
# 1. URL e sha256 publicados em https://developer.android.com/studio (tabela "Command line tools only")
mkdir -p "$TMP/dl" && cd "$TMP/dl"
curl -sSfLO https://dl.google.com/android/repository/commandlinetools-linux-15859902_latest.zip
echo "4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583  commandlinetools-linux-15859902_latest.zip" \
  | sha256sum -c -                                   # SUCESSO

# 2. O zip traz cmdline-tools/; o sdkmanager exige o layout cmdline-tools/latest
unzip -q commandlinetools-linux-15859902_latest.zip -d x
mkdir -p ~/Android/Sdk/cmdline-tools
mv x/cmdline-tools ~/Android/Sdk/cmdline-tools/latest

# 3. sdkmanager com o JBR 21
export JAVA_HOME=/opt/android-studio/jbr ANDROID_HOME=$HOME/Android/Sdk
SM=$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager
$SM --version                                        # 22.0
$SM --licenses </dev/null                            # "7 of 8 SDK package licenses not accepted" (nada aceito)
$SM --install "platforms;android-36" "build-tools;36.0.0" </dev/null
$SM --list_installed
```

O `sdkmanager` 22.0 avisa que está obsoleto em favor de `android sdk` (mesmo diretório `bin/`);
continua funcionando e é o que o CI e a documentação do AGP usam.

## Licenças

Só a `android-sdk-license` está aceita (aceita antes pelo Android Studio; cobre plataforma,
build-tools e platform-tools). As outras 7 (preview, NDK/ARM/Intel images, Google TV etc.) **não**
foram aceitas por agente. Se algum pacote futuro pedir, o Pedro roda à mão:

```sh
JAVA_HOME=/opt/android-studio/jbr ~/Android/Sdk/cmdline-tools/latest/bin/sdkmanager --licenses
```

## O que não vai ao git

`.gitignore`: `android/local.properties`, `android/**/build/`, `android/.gradle/`, `*.jks`,
`*.keystore`, `*.apk`.
