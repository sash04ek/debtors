#!/bin/sh
# Добавляет в Info.plist собранного macOS-приложения типы документов Excel (.xlsx/.xls/.xlsm),
# чтобы файлы можно было бросать на значок программы и открывать через «Открыть в…».
# Использование: ./add_document_types.sh "dist/Должники.app"
set -e
APP="$1"
PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Delete :CFBundleDocumentTypes" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes array" \
  -c "Add :CFBundleDocumentTypes:0 dict" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeName string Excel" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Viewer" \
  -c "Add :CFBundleDocumentTypes:0:LSHandlerRank string Alternate" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions array" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions:0 string xlsx" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions:1 string xls" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions:2 string xlsm" "$PLIST"
codesign --force --deep --sign - "$APP" 2>/dev/null || true       # изменение plist ломает подпись — подписываем заново
