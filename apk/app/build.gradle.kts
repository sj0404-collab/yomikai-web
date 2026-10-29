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
        // versionCode растёт с каждой сборкой: иначе установка «поверх» может
        // быть отвергнута как «та же версия».
        versionCode = 41
        versionName = "1.9.41"

        // Версию читалки знает только сам html. Читаем её при сборке и зашиваем
        // в BuildConfig — чтобы при старте не перечитывать 11 МБ ради сравнения
        // с тегом релиза на GitHub.
        val pageHtml = rootProject.file("../koma-web.html")
        val pageVer = if (pageHtml.exists())
            Regex("VERSION = '(v[0-9.]+)'").find(pageHtml.readText())?.groupValues?.get(1) ?: "unknown"
        else "unknown"
        buildConfigField("String", "PAGE_VERSION", "\"$pageVer\"")
    }

    /**
     * ОДИН постоянный ключ на все сборки.
     *
     * Почему это важно: раньше подпись бралась из отладочного хранилища, а оно на
     * каждом ранере GitHub создаётся заново с другим ключом. Из-за этого каждая
     * новая сборка была «другим приложением»: Android отказывался ставить её
     * поверх («Приложение не установлено»), и приходилось каждый раз удалять
     * старое. Теперь ключ лежит в репозитории и одинаков для всех сборок, поэтому
     * обновления встают поверх, а данные (модели, книги, настройки) остаются.
     */
    signingConfigs {
        create("koma") {
            storeFile = rootProject.file("keys/koma.jks")
            storePassword = "koma-reader-2026"
            keyAlias = "koma"
            keyPassword = "koma-reader-2026"
        }
    }

    // Оставляем только телефонные ABI: с полным набором (x86_64 и т.д.) АПК
    // распухал бы на десятки мегабайт без пользы для телефона.
    defaultConfig {
        // Только 64-битные ARM: библиотеки ONNX Runtime на каждый ABI — это ~12 МБ,
        // а в сборке ещё и модели на 12,6 МБ. С двумя ABI APK выходит за 50 МБ.
        // 32-битные телефоны (до ~2019) остаются без нативного распознавания —
        // там страница сама уйдёт на WASM, чтение не пропадёт.
        ndk { abiFilters += listOf("arm64-v8a") }
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("koma")
        }
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("koma")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    buildFeatures { buildConfig = true }
}

dependencies {
    // Только то, что нужно: WebViewAssetLoader. Ни appcompat, ни material —
    // интерфейс целиком рисует сама читалка, а меньше зависимостей = быстрее
    // и меньше АПК.
    implementation("androidx.webkit:webkit:1.11.0")
    // Нативное распознавание: те же ONNX-модели, но без WebAssembly.
    // ONNX Runtime для Android считает на CPU-ядрах телефона (и умеет NNAPI),
    // поэтому это быстрее браузерного WASM и не требует 11 МБ движка в html.
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.18.0")
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
