plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

// Assinatura do release só com as 4 variáveis no ambiente (spec §1); sem elas sai sem assinatura.
val chavesAssinatura = listOf("CONDESSA_KEYSTORE", "CONDESSA_KEYSTORE_SENHA", "CONDESSA_KEY_ALIAS", "CONDESSA_KEY_SENHA")
val assinar = chavesAssinatura.all { !System.getenv(it).isNullOrBlank() }
val ehRelease = gradle.startParameter.taskNames.any { it.contains("Release", ignoreCase = true) }

android {
    namespace = "br.com.dekasis.condessa"
    compileSdk = 36

    defaultConfig {
        applicationId = "br.com.dekasis.condessa"
        minSdk = 29
        targetSdk = 36
        versionCode = (findProperty("vc") as String? ?: "1").toInt()
        versionName = findProperty("vn") as String? ?: "0.0.0-dev"
    }

    signingConfigs {
        if (assinar) {
            create("release") {
                storeFile = file(System.getenv("CONDESSA_KEYSTORE"))
                storePassword = System.getenv("CONDESSA_KEYSTORE_SENHA")
                keyAlias = System.getenv("CONDESSA_KEY_ALIAS")
                keyPassword = System.getenv("CONDESSA_KEY_SENHA")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (assinar) signingConfig = signingConfigs.getByName("release")
        }
        debug {
            isMinifyEnabled = false
        }
    }

    splits {
        abi {
            // Só no release (spec §1): o debug roda no emulador x86_64 também.
            isEnable = ehRelease
            reset()
            include("arm64-v8a")
            isUniversalApk = false
        }
    }

    // RNF-C2: o libonnxruntime.so (28 MB) vai comprimido no APK (≈ metade); extraído na instalação.
    packaging { jniLibs { useLegacyPackaging = true } }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true }
    testOptions { unitTests.isIncludeAndroidResources = true }
    lint {
        abortOnError = true
        checkDependencies = false
    }
}

kotlin { jvmToolchain(21) }

// CA-M2: o teste lê o manifesto mesclado do debug.
tasks.withType<Test>().configureEach {
    dependsOn("processDebugMainManifest")
    systemProperty(
        "condessa.manifesto",
        layout.buildDirectory.file("intermediates/merged_manifest/debug/processDebugMainManifest/AndroidManifest.xml")
            .get().asFile.absolutePath,
    )
}

dependencies {
    implementation(project(":retrato"))
    implementation(project(":voz"))
    implementation(project(":rede"))

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.activity.compose)
    implementation(libs.core.ktx)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.navigation.compose)
    implementation(libs.datastore.preferences)
    implementation(libs.work.runtime.ktx)
    implementation(libs.unifiedpush.connector)
    implementation(libs.media3.session)
    implementation(libs.kotlinx.coroutines.android)
    debugImplementation(libs.compose.ui.tooling)
    debugImplementation(libs.compose.ui.test.manifest)

    testImplementation(libs.junit)
    testImplementation(libs.robolectric)
    testImplementation(libs.turbine)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.androidx.test.ext.junit)
    testImplementation(platform(libs.compose.bom))
    testImplementation(libs.compose.ui.test.junit4)
}
