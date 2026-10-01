plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "app.paisapeek"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.paisapeek"
        minSdk = 26
        targetSdk = 36
        // CI passes these from the git tag (v1.2.3 -> 1.2.3 / 10203); local builds stay 0.1-dev.
        versionCode = (findProperty("versionCode") as String?)?.toInt() ?: 1
        versionName = (findProperty("versionName") as String?) ?: "0.1-dev"
        manifestPlaceholders["appLabel"] = "Paisapeek"
    }

    signingConfigs {
        // Release key from the environment (CI secrets, see android/README.md). Every release must use the
        // same key, or phones refuse to install the update over the old app.
        System.getenv("ANDROID_KEYSTORE")?.let { path ->
            create("release") {
                storeFile = file(path)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release { signingConfig = signingConfigs.findByName("release") }
        // Separate app id so a debug build installs next to the released app instead of clashing with it.
        debug {
            applicationIdSuffix = ".debug"
            manifestPlaceholders["appLabel"] = "Paisapeek (debug)"
        }
    }

    buildFeatures { compose = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }

dependencies {
    implementation("androidx.work:work-runtime-ktx:2.10.5")
    implementation("androidx.activity:activity-compose:1.13.0")
    // Material 3 Expressive (button groups, loading indicator, flexible app bars) is only in the 1.5 alphas;
    // alpha19+ needs AGP 9.1 + compileSdk 37.
    implementation("androidx.compose.material3:material3:1.5.0-alpha18")
    implementation("androidx.compose.material:material-icons-core:1.7.8")
}
