if [[ -z "${NDK_HOME-}" ]]; then
    NDK_HOME=$HOME/ndk/$NDK_VERSION
    echo "NDK_HOME environment variable is not set."
    if [ ! -d $NDK_HOME ]; then
        echo "Installing NDK $NDK_VERSION to $NDK_HOME"
        mkdir -p downloads
        
        if [ $(uname) = "Darwin" ]; then
            seven_zip=downloads/7zip/7zz
            if ! test -f $seven_zip; then
                echo "Installing 7-zip"
                mkdir -p $(dirname $seven_zip)
                cd $(dirname $seven_zip)
                curl -#OL https://www.7-zip.org/a/7z2301-mac.tar.xz
                tar -xf 7z2301-mac.tar.xz
                cd -
            fi

            ndk_dmg=android-ndk-$NDK_VERSION-darwin.dmg
            if ! test -f downloads/$ndk_dmg; then
                echo ">>> Downloading $ndk_dmg"
                curl -#L -o downloads/$ndk_dmg https://dl.google.com/android/repository/$ndk_dmg
            fi

            cd downloads
            $seven_zip x $ndk_dmg
            mkdir -p $(dirname $NDK_HOME)
            mv Android\ NDK\ */AndroidNDK*.app/Contents/NDK $NDK_HOME
            rm -rf Android\ NDK\ *
            cd -
        else
            ndk_zip=android-ndk-$NDK_VERSION-linux.zip
            if ! test -f downloads/$ndk_zip; then
                echo ">>> Downloading $ndk_zip"
                curl -#L -o downloads/$ndk_zip https://dl.google.com/android/repository/$ndk_zip
            fi
            cd downloads
            unzip -oq $ndk_zip
            mkdir -p $(dirname $NDK_HOME)
            mv android-ndk-$NDK_VERSION $NDK_HOME
            cd -
            echo "NDK installed to $NDK_HOME"
        fi
    else
        echo "NDK $NDK_VERSION is already installed in $NDK_HOME"
    fi
else
    echo "NDK home: $NDK_HOME"
fi