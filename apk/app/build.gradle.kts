plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "net.koma.reader"
    compileSdk = 34

    defaultConfig {
        applicationId = "net.koma.reader"
        minSdk = 24            // WebViewAssetLoader + современный WebView есть с 21, но 24 безопаснее
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Подпись отладочным ключом: АПК ставится и работает. Для публикации
            // в Play нужен свой keystore — см. README, шаг «Своя подпись».
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.webkit:webkit:1.11.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
}

/**
 * Читалка — это один html-файл. Чтобы не держать в репозитории две копии
 * (11 МБ), при сборке берём свежую из корня репозитория. Если файла нет —
 * сборка не падает: остаётся та копия, что уже лежит в assets.
 */
val copyWeb by tasks.registering(Copy::class) {
    val src = rootProject.file("../koma-web.html")
    if (src.exists()) {
        from(src)
        into(layout.projectDirectory.dir("src/main/assets"))
        rename { "koma-web.html" }
    }
}
tasks.named("preBuild") { dependsOn(copyWeb) }
