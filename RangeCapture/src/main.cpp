// RangeCapture - 範囲指定キャプチャ & 最前面表示ソフト
//
//  起動するとすぐにキャプチャモードに入り、ドラッグした範囲をキャプチャして
//  タイトルバーなし・最前面のウィンドウで同じ位置に表示する（青い枠線と影付き、左ドラッグで移動可）。
//  キャプチャ時に PNG で自動保存する。表示ウィンドウのメニューから次のキャプチャを始められる。
//
//  ・座標はすべて物理ピクセルで扱う（Per-Monitor DPI Aware V2）。
//    画面の拡大縮小 (125%, 150% ...) や DPI の異なる複数モニターでも、
//    選択範囲・キャプチャ画像・表示位置がずれない。
//  ・仮想スクリーン（全モニターを含む矩形）全体を覆ってキャプチャモードを表示する。

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX

#include <windows.h>
#include <windowsx.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <wincodec.h>
#include <dwmapi.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <cwchar>
#include <string>
#include <vector>

// ---------------------------------------------------------------------------
// 定数
// ---------------------------------------------------------------------------
static const wchar_t kAppName[]        = L"RangeCapture";
static const wchar_t kOverlayClass[]   = L"RangeCapture.Overlay";
static const wchar_t kViewerClass[]    = L"RangeCapture.Viewer";
static const wchar_t kIniSection[]     = L"Settings";
static const wchar_t kIniKeyFolder[]   = L"SaveFolder";

enum MenuId : UINT {
    IDM_NEW_CAPTURE = 1000,
    IDM_COPY = 1001,
    IDM_SAVEAS,
    IDM_CHANGE_FOLDER,
    IDM_CLOSE,
};

enum class ImageFormat { Png, Jpeg, Bmp };

// 古い SDK ヘッダーには無い値
#ifndef DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
#define DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 ((HANDLE)-4)
#endif
#ifndef WM_DPICHANGED
#define WM_DPICHANGED 0x02E0
#endif
static const DWORD kDwmWindowCornerPreference = 33;  // DWMWA_WINDOW_CORNER_PREFERENCE
static const DWORD kDwmCornerDoNotRound       = 1;   // DWMWCP_DONOTROUND
static const DWORD kDwmTransitionsForceDisabled = 3; // DWMWA_TRANSITIONS_FORCEDISABLED

// ---------------------------------------------------------------------------
// 32bpp トップダウン DIB（メモリ DC 付き）
// ---------------------------------------------------------------------------
struct Dib {
    HBITMAP  bmp = nullptr;
    HDC      dc = nullptr;
    HGDIOBJ  oldBmp = nullptr;
    uint32_t* bits = nullptr;  // 0x00RRGGBB (BGRA のバイト順)
    int      w = 0;
    int      h = 0;

    bool Create(int width, int height) {
        Destroy();
        BITMAPINFO bi = {};
        bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
        bi.bmiHeader.biWidth = width;
        bi.bmiHeader.biHeight = -height;  // トップダウン
        bi.bmiHeader.biPlanes = 1;
        bi.bmiHeader.biBitCount = 32;
        bi.bmiHeader.biCompression = BI_RGB;
        HDC screen = GetDC(nullptr);
        void* p = nullptr;
        bmp = CreateDIBSection(screen, &bi, DIB_RGB_COLORS, &p, nullptr, 0);
        dc = CreateCompatibleDC(screen);
        ReleaseDC(nullptr, screen);
        if (!bmp || !dc) {
            Destroy();
            return false;
        }
        oldBmp = SelectObject(dc, bmp);
        bits = static_cast<uint32_t*>(p);
        w = width;
        h = height;
        return true;
    }

    void Destroy() {
        if (dc) {
            if (oldBmp) SelectObject(dc, oldBmp);
            DeleteDC(dc);
        }
        if (bmp) DeleteObject(bmp);
        bmp = nullptr;
        dc = nullptr;
        oldBmp = nullptr;
        bits = nullptr;
        w = h = 0;
    }

    ~Dib() { Destroy(); }
};

// ---------------------------------------------------------------------------
// グローバル状態（1 プロセス = 1 回のキャプチャ）
// ---------------------------------------------------------------------------
static HINSTANCE    g_hInst = nullptr;
static std::wstring g_iniPath;
static std::wstring g_saveFolder;

// キャプチャモード
static HWND  g_overlay = nullptr;
static Dib   g_screen;        // 起動時に撮った仮想スクリーン全体
static Dib   g_dark;          // それを暗くしたもの
static POINT g_virtOrigin = {};
static bool  g_dragging = false;
static POINT g_dragStart = {};
static POINT g_dragCur = {};
static bool  g_overlayDone = false;  // true: キャプチャ成功で閉じる（終了しない）

// 表示ウィンドウ
static HWND         g_viewer = nullptr;
static Dib          g_image;  // キャプチャ画像
static std::wstring g_baseName;  // 日時ファイル名（拡張子なし）
static int          g_frame = 2;         // 画像の外側に付ける枠線の太さ（物理ピクセル）
static bool         g_moving = false;    // 左ドラッグで移動中
static POINT        g_moveCursor0 = {};  // 移動開始時のカーソル位置（画面座標）
static POINT        g_moveWindow0 = {};  // 移動開始時のウィンドウ位置

static const UINT_PTR kTimerNewCapture = 1;
static const LPARAM   kFromKeyboard = 1;  // WM_COMMAND の lParam: キー操作から

// ---------------------------------------------------------------------------
// ユーティリティ
// ---------------------------------------------------------------------------
static bool DirectoryExists(const std::wstring& path) {
    if (path.empty()) return false;
    DWORD a = GetFileAttributesW(path.c_str());
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}

static bool FileExists(const std::wstring& path) {
    return GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES;
}

static std::wstring JoinPath(const std::wstring& dir, const std::wstring& name) {
    if (dir.empty()) return name;
    wchar_t last = dir.back();
    if (last == L'\\' || last == L'/') return dir + name;
    return dir + L"\\" + name;
}

static std::wstring ToLower(std::wstring s) {
    for (auto& c : s) c = static_cast<wchar_t>(towlower(c));
    return s;
}

static std::wstring Extension(const std::wstring& path) {
    size_t slash = path.find_last_of(L"\\/");
    size_t dot = path.find_last_of(L'.');
    if (dot == std::wstring::npos || (slash != std::wstring::npos && dot < slash)) return L"";
    return ToLower(path.substr(dot));
}

static void ShowError(HWND owner, const std::wstring& msg) {
    MessageBoxW(owner, msg.c_str(), kAppName, MB_OK | MB_ICONERROR | MB_TOPMOST);
}

static std::wstring HResultText(HRESULT hr) {
    wchar_t buf[32];
    swprintf(buf, 32, L"0x%08lX", static_cast<unsigned long>(hr));
    std::wstring s = buf;
    wchar_t* msg = nullptr;
    if (FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                           FORMAT_MESSAGE_IGNORE_INSERTS,
                       nullptr, static_cast<DWORD>(hr), 0, reinterpret_cast<LPWSTR>(&msg), 0,
                       nullptr) && msg) {
        s += L" ";
        s += msg;
        LocalFree(msg);
    }
    return s;
}

// 日時のファイル名（例: 20261120_153012_345）
static std::wstring TimestampName() {
    SYSTEMTIME st;
    GetLocalTime(&st);
    wchar_t buf[64];
    swprintf(buf, 64, L"%04u%02u%02u_%02u%02u%02u_%03u", st.wYear, st.wMonth, st.wDay, st.wHour,
             st.wMinute, st.wSecond, st.wMilliseconds);
    return buf;
}

static void DisableDwmEffects(HWND hwnd) {
    // Windows 11 の角丸と、表示/非表示時のフェードアニメーションを無効にする
    DWORD corner = kDwmCornerDoNotRound;
    DwmSetWindowAttribute(hwnd, kDwmWindowCornerPreference, &corner, sizeof(corner));
    BOOL disable = TRUE;
    DwmSetWindowAttribute(hwnd, kDwmTransitionsForceDisabled, &disable, sizeof(disable));
}

static const COLORREF kFrameColor = RGB(0, 120, 215);  // 選択範囲・表示ウィンドウの枠線の色

// outer の内側に太さ t の枠を塗る
static void FillFrame(HDC dc, const RECT& outer, int t, COLORREF color) {
    HBRUSH br = CreateSolidBrush(color);
    RECT r;
    SetRect(&r, outer.left, outer.top, outer.right, outer.top + t);
    FillRect(dc, &r, br);
    SetRect(&r, outer.left, outer.bottom - t, outer.right, outer.bottom);
    FillRect(dc, &r, br);
    SetRect(&r, outer.left, outer.top, outer.left + t, outer.bottom);
    FillRect(dc, &r, br);
    SetRect(&r, outer.right - t, outer.top, outer.right, outer.bottom);
    FillRect(dc, &r, br);
    DeleteObject(br);
}

// ---------------------------------------------------------------------------
// DPI
// ---------------------------------------------------------------------------
// 矩形があるモニターの DPI（拡大率 100% = 96）
static UINT DpiForRect(const RECT& r) {
    HMONITOR mon = MonitorFromRect(&r, MONITOR_DEFAULTTONEAREST);
    using GetDpiForMonitorFn = HRESULT(WINAPI*)(HMONITOR, int, UINT*, UINT*);
    static HMODULE shcore = LoadLibraryW(L"shcore.dll");
    if (shcore) {
        auto fn = reinterpret_cast<GetDpiForMonitorFn>(
            reinterpret_cast<void*>(GetProcAddress(shcore, "GetDpiForMonitor")));
        UINT dx = 0, dy = 0;
        if (fn && SUCCEEDED(fn(mon, 0 /* MDT_EFFECTIVE_DPI */, &dx, &dy)) && dx) return dx;
    }
    HDC dc = GetDC(nullptr);
    int d = GetDeviceCaps(dc, LOGPIXELSX);
    ReleaseDC(nullptr, dc);
    return d > 0 ? static_cast<UINT>(d) : 96;
}

static void EnableDpiAwareness() {
    // 通常はマニフェストで PerMonitorV2 が設定済み。念のため実行時にも設定する。
    HMODULE user32 = GetModuleHandleW(L"user32.dll");
    using SetCtxFn = BOOL(WINAPI*)(HANDLE);
    auto setCtx = reinterpret_cast<SetCtxFn>(
        reinterpret_cast<void*>(GetProcAddress(user32, "SetProcessDpiAwarenessContext")));
    if (setCtx && setCtx(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)) return;
    if (setCtx && GetLastError() == ERROR_ACCESS_DENIED) return;  // 既に設定済み
    using SetAwareFn = BOOL(WINAPI*)();
    auto setAware = reinterpret_cast<SetAwareFn>(
        reinterpret_cast<void*>(GetProcAddress(user32, "SetProcessDPIAware")));
    if (setAware) setAware();
}

// ---------------------------------------------------------------------------
// 設定ファイル（%APPDATA%\RangeCapture\settings.ini）
// ---------------------------------------------------------------------------
static void InitIniPath() {
    PWSTR appData = nullptr;
    if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_RoamingAppData, 0, nullptr, &appData)) && appData) {
        std::wstring dir = JoinPath(appData, kAppName);
        CoTaskMemFree(appData);
        CreateDirectoryW(dir.c_str(), nullptr);
        g_iniPath = JoinPath(dir, L"settings.ini");
    } else {
        // 取得できなければ exe と同じフォルダ
        wchar_t exe[MAX_PATH] = {};
        GetModuleFileNameW(nullptr, exe, MAX_PATH);
        std::wstring p = exe;
        size_t pos = p.find_last_of(L"\\/");
        g_iniPath = JoinPath(pos == std::wstring::npos ? L"." : p.substr(0, pos), L"settings.ini");
    }
}

static void LoadSettings() {
    wchar_t buf[4096] = {};
    GetPrivateProfileStringW(kIniSection, kIniKeyFolder, L"", buf, 4096, g_iniPath.c_str());
    g_saveFolder = buf;
}

static bool SaveSettings() {
    // 日本語などを含むパスを正しく保存するため、ファイルを UTF-16LE (BOM 付き) で作っておく。
    // （BOM 付き UTF-16 の INI には WritePrivateProfileStringW が Unicode で書き込む）
    if (!FileExists(g_iniPath)) {
        HANDLE f = CreateFileW(g_iniPath.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                               FILE_ATTRIBUTE_NORMAL, nullptr);
        if (f != INVALID_HANDLE_VALUE) {
            const unsigned char bom[2] = {0xFF, 0xFE};
            DWORD written = 0;
            WriteFile(f, bom, 2, &written, nullptr);
            CloseHandle(f);
        }
    }
    BOOL ok = WritePrivateProfileStringW(kIniSection, kIniKeyFolder, g_saveFolder.c_str(),
                                         g_iniPath.c_str());
    // すぐに次の exe を起動しても読めるよう、キャッシュをファイルへ書き出す
    WritePrivateProfileStringW(nullptr, nullptr, nullptr, g_iniPath.c_str());
    return ok != FALSE;
}

// ---------------------------------------------------------------------------
// フォルダ選択ダイアログ
// ---------------------------------------------------------------------------
static bool PickFolder(HWND owner, const std::wstring& initial, std::wstring& result) {
    IFileOpenDialog* dlg = nullptr;
    if (FAILED(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(&dlg))))
        return false;
    bool ok = false;
    DWORD opts = 0;
    dlg->GetOptions(&opts);
    dlg->SetOptions(opts | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST);
    dlg->SetTitle(L"キャプチャ画像の保存先フォルダを選択してください");
    if (DirectoryExists(initial)) {
        IShellItem* folder = nullptr;
        if (SUCCEEDED(SHCreateItemFromParsingName(initial.c_str(), nullptr, IID_PPV_ARGS(&folder)))) {
            dlg->SetFolder(folder);
            folder->Release();
        }
    }
    if (SUCCEEDED(dlg->Show(owner))) {
        IShellItem* item = nullptr;
        if (SUCCEEDED(dlg->GetResult(&item))) {
            PWSTR path = nullptr;
            if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &path)) && path) {
                result = path;
                CoTaskMemFree(path);
                ok = true;
            }
            item->Release();
        }
    }
    dlg->Release();
    return ok;
}

// ---------------------------------------------------------------------------
// 画像の保存（WIC）
// ---------------------------------------------------------------------------
static HRESULT SaveImageFile(const std::wstring& path, const Dib& img, ImageFormat fmt) {
    if (!img.bits) return E_POINTER;
    IWICImagingFactory* factory = nullptr;
    IWICStream* stream = nullptr;
    IWICBitmapEncoder* encoder = nullptr;
    IWICBitmapFrameEncode* frame = nullptr;
    IPropertyBag2* props = nullptr;
    IWICBitmap* source = nullptr;
    bool fileCreated = false;

    HRESULT hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                                  IID_PPV_ARGS(&factory));
    if (SUCCEEDED(hr)) hr = factory->CreateStream(&stream);
    if (SUCCEEDED(hr)) hr = stream->InitializeFromFilename(path.c_str(), GENERIC_WRITE);
    if (SUCCEEDED(hr)) {
        fileCreated = true;
        const GUID& container = fmt == ImageFormat::Jpeg ? GUID_ContainerFormatJpeg
                                : fmt == ImageFormat::Bmp ? GUID_ContainerFormatBmp
                                                          : GUID_ContainerFormatPng;
        hr = factory->CreateEncoder(container, nullptr, &encoder);
    }
    if (SUCCEEDED(hr)) hr = encoder->Initialize(stream, WICBitmapEncoderNoCache);
    if (SUCCEEDED(hr)) hr = encoder->CreateNewFrame(&frame, &props);
    if (SUCCEEDED(hr) && fmt == ImageFormat::Jpeg && props) {
        PROPBAG2 opt = {};
        opt.pstrName = const_cast<LPOLESTR>(L"ImageQuality");
        VARIANT v;
        VariantInit(&v);
        v.vt = VT_R4;
        v.fltVal = 0.92f;
        props->Write(1, &opt, &v);  // 失敗しても既定の画質で続行
    }
    if (SUCCEEDED(hr)) hr = frame->Initialize(props);
    if (SUCCEEDED(hr)) hr = frame->SetSize(static_cast<UINT>(img.w), static_cast<UINT>(img.h));
    if (SUCCEEDED(hr)) {
        WICPixelFormatGUID pf = GUID_WICPixelFormat24bppBGR;
        hr = frame->SetPixelFormat(&pf);
    }
    if (SUCCEEDED(hr)) {
        hr = factory->CreateBitmapFromMemory(
            static_cast<UINT>(img.w), static_cast<UINT>(img.h), GUID_WICPixelFormat32bppBGR,
            static_cast<UINT>(img.w * 4), static_cast<UINT>(img.w * 4 * img.h),
            reinterpret_cast<BYTE*>(img.bits), &source);
    }
    if (SUCCEEDED(hr)) hr = frame->WriteSource(source, nullptr);  // 24bpp へ変換して書き込み
    if (SUCCEEDED(hr)) hr = frame->Commit();
    if (SUCCEEDED(hr)) hr = encoder->Commit();

    if (source) source->Release();
    if (props) props->Release();
    if (frame) frame->Release();
    if (encoder) encoder->Release();
    if (stream) stream->Release();
    if (factory) factory->Release();
    if (FAILED(hr) && fileCreated) DeleteFileW(path.c_str());
    return hr;
}

// 自動保存（保存先フォルダに 日時.png）
static void AutoSave(HWND owner) {
    if (!DirectoryExists(g_saveFolder)) {
        ShowError(owner, L"保存先フォルダが見つからないため、自動保存できませんでした。\n\n" +
                             g_saveFolder +
                             L"\n\n右クリックメニューの「保存先フォルダの変更」で設定し直してください。");
        return;
    }
    std::wstring path = JoinPath(g_saveFolder, g_baseName + L".png");
    // 同じミリ秒に別のプロセスが保存した場合などに備えて重複を避ける
    for (int i = 2; FileExists(path) && i < 1000; ++i)
        path = JoinPath(g_saveFolder, g_baseName + L"_" + std::to_wstring(i) + L".png");
    HRESULT hr = SaveImageFile(path, g_image, ImageFormat::Png);
    if (FAILED(hr)) ShowError(owner, L"自動保存に失敗しました。\n\n" + path + L"\n\n" + HResultText(hr));
}

// ---------------------------------------------------------------------------
// クリップボードへコピー（CF_DIB 24bpp）
// ---------------------------------------------------------------------------
static bool CopyToClipboard(HWND owner, const Dib& img) {
    if (!img.bits) return false;
    const int stride = ((img.w * 3) + 3) & ~3;
    const SIZE_T size = sizeof(BITMAPINFOHEADER) + static_cast<SIZE_T>(stride) * img.h;
    HGLOBAL mem = GlobalAlloc(GMEM_MOVEABLE, size);
    if (!mem) return false;
    auto* p = static_cast<BYTE*>(GlobalLock(mem));
    auto* bih = reinterpret_cast<BITMAPINFOHEADER*>(p);
    std::memset(bih, 0, sizeof(*bih));
    bih->biSize = sizeof(BITMAPINFOHEADER);
    bih->biWidth = img.w;
    bih->biHeight = img.h;  // ボトムアップ
    bih->biPlanes = 1;
    bih->biBitCount = 24;
    bih->biCompression = BI_RGB;
    bih->biSizeImage = static_cast<DWORD>(stride * img.h);
    BYTE* pixels = p + sizeof(BITMAPINFOHEADER);
    for (int y = 0; y < img.h; ++y) {
        const uint32_t* src = img.bits + static_cast<size_t>(img.h - 1 - y) * img.w;
        BYTE* dst = pixels + static_cast<size_t>(y) * stride;
        for (int x = 0; x < img.w; ++x) {
            uint32_t c = src[x];
            dst[x * 3 + 0] = static_cast<BYTE>(c & 0xFF);
            dst[x * 3 + 1] = static_cast<BYTE>((c >> 8) & 0xFF);
            dst[x * 3 + 2] = static_cast<BYTE>((c >> 16) & 0xFF);
        }
        for (int x = img.w * 3; x < stride; ++x) dst[x] = 0;
    }
    GlobalUnlock(mem);

    bool ok = false;
    for (int retry = 0; retry < 10 && !ok; ++retry) {  // 他のアプリが開いている場合に備えて再試行
        if (OpenClipboard(owner)) {
            EmptyClipboard();
            ok = SetClipboardData(CF_DIB, mem) != nullptr;
            CloseClipboard();
        } else {
            Sleep(30);
        }
    }
    if (!ok) GlobalFree(mem);
    return ok;
}

// ---------------------------------------------------------------------------
// 名前を付けて保存
// ---------------------------------------------------------------------------
static void SaveAs(HWND owner) {
    LoadSettings();  // 別に起動した exe で保存先が変更されている場合に備えて読み直す
    IFileSaveDialog* dlg = nullptr;
    if (FAILED(CoCreateInstance(CLSID_FileSaveDialog, nullptr, CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(&dlg))))
        return;
    static const COMDLG_FILTERSPEC types[] = {
        {L"PNG 画像 (*.png)", L"*.png"},
        {L"JPEG 画像 (*.jpg;*.jpeg)", L"*.jpg;*.jpeg"},
        {L"BMP 画像 (*.bmp)", L"*.bmp"},
    };
    dlg->SetFileTypes(3, types);
    dlg->SetFileTypeIndex(1);
    // SetDefaultExtension は使わない（「a.jpg」と入力しても種類が PNG だと「a.jpg.png」に
    // なる環境があるため）。拡張子はダイアログを閉じた後にこちらで決める。
    dlg->SetFileName(g_baseName.c_str());
    dlg->SetTitle(L"名前を付けて保存");
    DWORD opts = 0;
    dlg->GetOptions(&opts);
    dlg->SetOptions(opts | FOS_OVERWRITEPROMPT | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST);
    if (DirectoryExists(g_saveFolder)) {
        IShellItem* folder = nullptr;
        if (SUCCEEDED(SHCreateItemFromParsingName(g_saveFolder.c_str(), nullptr,
                                                  IID_PPV_ARGS(&folder)))) {
            dlg->SetFolder(folder);
            folder->Release();
        }
    }

    std::wstring path;
    UINT typeIndex = 1;
    if (SUCCEEDED(dlg->Show(owner))) {
        dlg->GetFileTypeIndex(&typeIndex);
        IShellItem* item = nullptr;
        if (SUCCEEDED(dlg->GetResult(&item))) {
            PWSTR p = nullptr;
            if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &p)) && p) {
                path = p;
                CoTaskMemFree(p);
            }
            item->Release();
        }
    }
    dlg->Release();
    if (path.empty()) return;

    // 形式は拡張子で決める。拡張子が無い/不明なら選択中の種類で決めて拡張子を付ける。
    ImageFormat fmt;
    std::wstring ext = Extension(path);
    if (ext == L".png") {
        fmt = ImageFormat::Png;
    } else if (ext == L".jpg" || ext == L".jpeg") {
        fmt = ImageFormat::Jpeg;
    } else if (ext == L".bmp") {
        fmt = ImageFormat::Bmp;
    } else {
        fmt = typeIndex == 2 ? ImageFormat::Jpeg : typeIndex == 3 ? ImageFormat::Bmp : ImageFormat::Png;
        path += fmt == ImageFormat::Jpeg ? L".jpg" : fmt == ImageFormat::Bmp ? L".bmp" : L".png";
        // 拡張子を付け足した名前はダイアログの上書き確認の対象外なので、ここで確認する
        if (FileExists(path)) {
            std::wstring q = path + L" は既に存在します。\n上書きしますか？";
            if (MessageBoxW(owner, q.c_str(), L"名前を付けて保存",
                            MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2) != IDYES)
                return;
        }
    }
    HRESULT hr = SaveImageFile(path, g_image, fmt);
    if (FAILED(hr)) ShowError(owner, L"保存に失敗しました。\n\n" + path + L"\n\n" + HResultText(hr));
}

static void ChangeSaveFolder(HWND owner) {
    LoadSettings();
    std::wstring folder;
    if (!PickFolder(owner, g_saveFolder, folder)) return;
    g_saveFolder = folder;
    if (!SaveSettings())
        ShowError(owner, L"設定ファイルに保存できませんでした。\n\n" + g_iniPath);
}

// ---------------------------------------------------------------------------
// 表示ウィンドウ（タイトルバーなし・枠線と影付き・最前面・キャプチャ位置に表示）
// ---------------------------------------------------------------------------
// 新しいキャプチャを始める（自分の exe をもう一度起動する。今の表示ウィンドウはそのまま残る）
static void LaunchNewCapture(HWND owner) {
    std::vector<wchar_t> exe(32768);
    DWORD len = GetModuleFileNameW(nullptr, exe.data(), static_cast<DWORD>(exe.size()));
    if (len == 0 || len >= exe.size()) {
        ShowError(owner, L"新しいキャプチャを開始できませんでした。");
        return;
    }
    std::wstring cmd = L"\"" + std::wstring(exe.data()) + L"\"";
    std::vector<wchar_t> cmdBuf(cmd.begin(), cmd.end());
    cmdBuf.push_back(L'\0');
    STARTUPINFOW si = {};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi = {};
    AllowSetForegroundWindow(ASFW_ANY);  // 新しいキャプチャ画面が前面に出られるように
    if (!CreateProcessW(exe.data(), cmdBuf.data(), nullptr, nullptr, FALSE, 0, nullptr, nullptr,
                        &si, &pi)) {
        ShowError(owner, L"新しいキャプチャを開始できませんでした。\n\n" +
                             HResultText(HRESULT_FROM_WIN32(GetLastError())));
        return;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
}

static void ShowViewerMenu(HWND hwnd, int x, int y) {
    HMENU menu = CreatePopupMenu();
    AppendMenuW(menu, MF_STRING, IDM_NEW_CAPTURE, L"新しくキャプチャ(&N)\tN");
    AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(menu, MF_STRING, IDM_COPY, L"コピー(&C)\tCtrl+C");
    AppendMenuW(menu, MF_STRING, IDM_SAVEAS, L"名前を付けて保存(&S)...\tCtrl+S");
    AppendMenuW(menu, MF_STRING, IDM_CHANGE_FOLDER, L"保存先フォルダの変更(&F)...");
    AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(menu, MF_STRING, IDM_CLOSE, L"閉じる(&X)\tEsc");
    SetForegroundWindow(hwnd);
    UINT cmd = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY, x, y, 0, hwnd,
                              nullptr);
    DestroyMenu(menu);
    if (cmd) PostMessageW(hwnd, WM_COMMAND, cmd, 0);
}

static LRESULT CALLBACK ViewerProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE:
        DisableDwmEffects(hwnd);
        return 0;

    case WM_ERASEBKGND:
        return 1;

    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hwnd, &ps);
        BitBlt(hdc, g_frame, g_frame, g_image.w, g_image.h, g_image.dc, 0, 0, SRCCOPY);
        RECT rc;
        GetClientRect(hwnd, &rc);
        FillFrame(hdc, rc, g_frame, kFrameColor);
        EndPaint(hwnd, &ps);
        return 0;
    }

    case WM_CONTEXTMENU: {
        int x = GET_X_LPARAM(lp);
        int y = GET_Y_LPARAM(lp);
        if (x == -1 && y == -1) {  // キーボード（アプリケーションキー / Shift+F10）
            RECT rc;
            GetWindowRect(hwnd, &rc);
            x = rc.left;
            y = rc.top;
        }
        ShowViewerMenu(hwnd, x, y);
        return 0;
    }

    // 左ドラッグでウィンドウを移動する（物理ピクセルの画面座標で計算するので、
    // 拡大率の違うモニターへ移しても画像は等倍のまま）
    case WM_LBUTTONDOWN: {
        RECT rc;
        GetWindowRect(hwnd, &rc);
        GetCursorPos(&g_moveCursor0);
        g_moveWindow0.x = rc.left;
        g_moveWindow0.y = rc.top;
        g_moving = true;
        SetCapture(hwnd);
        return 0;
    }

    case WM_MOUSEMOVE:
        if (g_moving) {
            POINT p;
            GetCursorPos(&p);
            SetWindowPos(hwnd, nullptr, g_moveWindow0.x + (p.x - g_moveCursor0.x),
                         g_moveWindow0.y + (p.y - g_moveCursor0.y), 0, 0,
                         SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
        }
        return 0;

    case WM_LBUTTONUP:
        if (g_moving) {
            g_moving = false;
            ReleaseCapture();
        }
        return 0;

    case WM_CAPTURECHANGED:
        g_moving = false;
        return 0;

    case WM_TIMER:
        if (wp == kTimerNewCapture) {
            KillTimer(hwnd, kTimerNewCapture);
            LaunchNewCapture(hwnd);
        }
        return 0;

    case WM_KEYDOWN: {
        bool ctrl = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        if (wp == VK_ESCAPE) {
            PostMessageW(hwnd, WM_COMMAND, IDM_CLOSE, 0);
        } else if (wp == 'N') {
            PostMessageW(hwnd, WM_COMMAND, IDM_NEW_CAPTURE, kFromKeyboard);
        } else if (ctrl && wp == 'C') {
            PostMessageW(hwnd, WM_COMMAND, IDM_COPY, 0);
        } else if (ctrl && wp == 'S') {
            PostMessageW(hwnd, WM_COMMAND, IDM_SAVEAS, 0);
        }
        return 0;
    }

    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case IDM_NEW_CAPTURE:
            // メニューから選んだときは、メニューが消えきってから起動する
            // （新しいキャプチャが最初に撮る画面に、消えかけのメニューが写らないように）
            SetTimer(hwnd, kTimerNewCapture, lp == kFromKeyboard ? 10 : 300, nullptr);
            return 0;
        case IDM_COPY:
            if (!CopyToClipboard(hwnd, g_image))
                ShowError(hwnd, L"クリップボードへのコピーに失敗しました。");
            return 0;
        case IDM_SAVEAS:
            SaveAs(hwnd);
            return 0;
        case IDM_CHANGE_FOLDER:
            ChangeSaveFolder(hwnd);
            return 0;
        case IDM_CLOSE:
            DestroyWindow(hwnd);
            return 0;
        }
        break;

    case WM_DPICHANGED:
        // 画像は等倍（物理ピクセル）で表示するので、DPI が変わってもサイズを変えない
        return 0;

    case WM_DESTROY:
        g_viewer = nullptr;
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

// imageRect: 画像を表示する画面上の位置（=キャプチャした位置）。枠線はその外側に付ける。
static bool CreateViewer(const RECT& imageRect) {
    // 枠線は拡大率 100% で 2 ピクセル。拡大率に合わせて太くする（150% なら 3 ピクセル）
    g_frame = std::max(2, MulDiv(2, static_cast<int>(DpiForRect(imageRect)), 96));
    RECT wr = imageRect;
    InflateRect(&wr, g_frame, g_frame);
    const int w = wr.right - wr.left;
    const int h = wr.bottom - wr.top;

    std::wstring title = std::wstring(kAppName) + L" - " + g_baseName;
    g_viewer = CreateWindowExW(WS_EX_TOPMOST, kViewerClass, title.c_str(), WS_POPUP, wr.left,
                               wr.top, w, h, nullptr, nullptr, g_hInst, nullptr);
    if (!g_viewer) return false;
    // 念のため物理ピクセルでの位置・サイズを確定させてから表示する
    SetWindowPos(g_viewer, HWND_TOPMOST, wr.left, wr.top, w, h, SWP_NOACTIVATE);
    ShowWindow(g_viewer, SW_SHOW);
    UpdateWindow(g_viewer);
    SetForegroundWindow(g_viewer);
    SetFocus(g_viewer);
    return true;
}

// ---------------------------------------------------------------------------
// キャプチャモード（全モニターを覆う暗いオーバーレイ）
// ---------------------------------------------------------------------------
// 押した点と現在の点の両方のピクセルを含む矩形（画面の右端・下端の 1 ピクセルまで選べるように）
static RECT SelectionRect() {
    RECT r;
    r.left = std::min(g_dragStart.x, g_dragCur.x);
    r.top = std::min(g_dragStart.y, g_dragCur.y);
    r.right = std::max(g_dragStart.x, g_dragCur.x) + 1;
    r.bottom = std::max(g_dragStart.y, g_dragCur.y) + 1;
    return r;
}

static POINT ClampToScreen(LPARAM lp) {
    POINT p;
    p.x = std::max(0, std::min(static_cast<int>(GET_X_LPARAM(lp)), g_screen.w - 1));
    p.y = std::max(0, std::min(static_cast<int>(GET_Y_LPARAM(lp)), g_screen.h - 1));
    return p;
}

static const int kBorder = 2;  // 枠線の太さ（選択範囲の外側に描く）

static void InvalidateSelection(HWND hwnd, const RECT& sel) {
    RECT r = sel;
    InflateRect(&r, kBorder + 1, kBorder + 1);
    InvalidateRect(hwnd, &r, FALSE);
}

static void FinishCapture(HWND overlay, const RECT& sel) {
    const int w = sel.right - sel.left;
    const int h = sel.bottom - sel.top;
    if (!g_image.Create(w, h)) {
        ShowError(overlay, L"メモリが不足しているため、キャプチャできませんでした。");
        DestroyWindow(overlay);
        return;
    }
    // 起動時に撮った画面から切り出す（オーバーレイの暗さや枠線は含まれない）
    BitBlt(g_image.dc, 0, 0, w, h, g_screen.dc, sel.left, sel.top, SRCCOPY);
    GdiFlush();
    g_baseName = TimestampName();

    RECT screenRect = sel;
    OffsetRect(&screenRect, g_virtOrigin.x, g_virtOrigin.y);
    if (!CreateViewer(screenRect)) {
        ShowError(overlay, L"表示ウィンドウを作成できませんでした。");
        DestroyWindow(overlay);
        return;
    }
    g_overlayDone = true;
    DestroyWindow(overlay);  // 表示ウィンドウを出してから消す（ちらつき防止）
    g_screen.Destroy();
    g_dark.Destroy();

    AutoSave(g_viewer);
}

static void CancelCapture(HWND overlay) {
    DestroyWindow(overlay);  // g_overlayDone == false なので終了する
}

static LRESULT CALLBACK OverlayProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE:
        DisableDwmEffects(hwnd);
        return 0;

    case WM_ERASEBKGND:
        return 1;

    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hwnd, &ps);
        const RECT rc = ps.rcPaint;
        const int w = rc.right - rc.left;
        const int h = rc.bottom - rc.top;
        if (w > 0 && h > 0) {
            // 更新範囲だけをバックバッファに描いてから転送する（ちらつき防止）
            HDC buf = CreateCompatibleDC(hdc);
            HBITMAP bb = CreateCompatibleBitmap(hdc, w, h);
            HGDIOBJ old = SelectObject(buf, bb);
            BitBlt(buf, 0, 0, w, h, g_dark.dc, rc.left, rc.top, SRCCOPY);
            if (g_dragging) {
                const RECT sel = SelectionRect();
                RECT is;
                if (IntersectRect(&is, &sel, &rc)) {
                    BitBlt(buf, is.left - rc.left, is.top - rc.top, is.right - is.left,
                           is.bottom - is.top, g_screen.dc, is.left, is.top, SRCCOPY);
                }
                // 枠線
                RECT o = sel;
                InflateRect(&o, kBorder, kBorder);
                OffsetRect(&o, -rc.left, -rc.top);
                FillFrame(buf, o, kBorder, kFrameColor);
            }
            BitBlt(hdc, rc.left, rc.top, w, h, buf, 0, 0, SRCCOPY);
            SelectObject(buf, old);
            DeleteObject(bb);
            DeleteDC(buf);
        }
        EndPaint(hwnd, &ps);
        return 0;
    }

    case WM_LBUTTONDOWN:
        g_dragging = true;
        g_dragStart = g_dragCur = ClampToScreen(lp);
        SetCapture(hwnd);
        InvalidateSelection(hwnd, SelectionRect());
        return 0;

    case WM_MOUSEMOVE:
        if (g_dragging) {
            RECT before = SelectionRect();
            g_dragCur = ClampToScreen(lp);
            RECT after = SelectionRect();
            RECT u;
            UnionRect(&u, &before, &after);
            InvalidateSelection(hwnd, u);
        }
        return 0;

    case WM_LBUTTONUP:
        if (g_dragging) {
            g_dragCur = ClampToScreen(lp);
            RECT sel = SelectionRect();
            const bool moved = g_dragCur.x != g_dragStart.x || g_dragCur.y != g_dragStart.y;
            g_dragging = false;
            ReleaseCapture();
            if (moved) {
                FinishCapture(hwnd, sel);
            } else {
                // ドラッグせずにクリックしただけのときは確定せず、選択をやり直す
                InvalidateSelection(hwnd, sel);
            }
        }
        return 0;

    case WM_CAPTURECHANGED:
        if (g_dragging && reinterpret_cast<HWND>(lp) != hwnd) {
            g_dragging = false;
            InvalidateRect(hwnd, nullptr, FALSE);
        }
        return 0;

    case WM_RBUTTONDOWN:
        return 0;  // 離したときに中止する（下のウィンドウに右ボタンアップが渡らないように）

    case WM_RBUTTONUP:
        CancelCapture(hwnd);
        return 0;

    case WM_KEYDOWN:
        if (wp == VK_ESCAPE) CancelCapture(hwnd);
        return 0;

    case WM_DPICHANGED:
        // 仮想スクリーン全体を物理ピクセルで覆っているので、サイズは変えない
        return 0;

    case WM_DESTROY:
        g_overlay = nullptr;
        if (!g_overlayDone) PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static bool StartCaptureMode() {
    const int vx = GetSystemMetrics(SM_XVIRTUALSCREEN);
    const int vy = GetSystemMetrics(SM_YVIRTUALSCREEN);
    const int vw = GetSystemMetrics(SM_CXVIRTUALSCREEN);
    const int vh = GetSystemMetrics(SM_CYVIRTUALSCREEN);
    g_virtOrigin.x = vx;
    g_virtOrigin.y = vy;

    // 画面全体を先に撮っておく（以後この画像から切り出す）
    if (!g_screen.Create(vw, vh) || !g_dark.Create(vw, vh)) {
        ShowError(nullptr, L"メモリが不足しているため、キャプチャモードを開始できませんでした。");
        return false;
    }
    HDC screen = GetDC(nullptr);
    BitBlt(g_screen.dc, 0, 0, vw, vh, screen, vx, vy, SRCCOPY | CAPTUREBLT);
    ReleaseDC(nullptr, screen);
    GdiFlush();

    // 暗い画像（各色 1/2）
    const size_t n = static_cast<size_t>(vw) * vh;
    for (size_t i = 0; i < n; ++i) g_dark.bits[i] = (g_screen.bits[i] >> 1) & 0x007F7F7F;

    g_overlay = CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, kOverlayClass, kAppName,
                                WS_POPUP, vx, vy, vw, vh, nullptr, nullptr, g_hInst, nullptr);
    if (!g_overlay) {
        ShowError(nullptr, L"キャプチャ用のウィンドウを作成できませんでした。");
        return false;
    }
    SetWindowPos(g_overlay, HWND_TOPMOST, vx, vy, vw, vh, SWP_NOACTIVATE);
    ShowWindow(g_overlay, SW_SHOW);
    UpdateWindow(g_overlay);
    SetForegroundWindow(g_overlay);
    SetFocus(g_overlay);
    return true;
}

// ---------------------------------------------------------------------------
// エントリポイント
// ---------------------------------------------------------------------------
static void PumpMessagesFor(DWORD ms) {
    const DWORD start = GetTickCount();
    MSG msg;
    while (GetTickCount() - start < ms) {
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        Sleep(10);
    }
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE, PWSTR, int) {
    g_hInst = hInst;
    EnableDpiAwareness();
    HRESULT hrCo = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);

    InitIniPath();
    LoadSettings();

    // 保存先が未設定（または存在しない）ならフォルダ選択画面を出す
    if (!DirectoryExists(g_saveFolder)) {
        std::wstring folder;
        if (!PickFolder(nullptr, g_saveFolder, folder)) {
            if (SUCCEEDED(hrCo)) CoUninitialize();
            return 0;  // キャンセルされたら終了
        }
        g_saveFolder = folder;
        if (!SaveSettings())
            ShowError(nullptr, L"設定ファイルに保存できませんでした。\n\n" + g_iniPath);
        // ダイアログが消えて下の画面が描き直されるのを待ってから画面を撮る
        PumpMessagesFor(300);
    }

    WNDCLASSEXW wc = {};
    wc.cbSize = sizeof(wc);
    wc.hInstance = hInst;
    wc.hIcon = LoadIconW(hInst, MAKEINTRESOURCEW(1));
    wc.hIconSm = wc.hIcon;

    wc.lpfnWndProc = OverlayProc;
    wc.hCursor = LoadCursorW(nullptr, IDC_CROSS);
    wc.lpszClassName = kOverlayClass;
    RegisterClassExW(&wc);

    wc.lpfnWndProc = ViewerProc;
    wc.style = CS_DROPSHADOW;  // 表示ウィンドウに影を付ける（Windows の「ウィンドウの下に影を表示する」設定に従う）
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.lpszClassName = kViewerClass;
    RegisterClassExW(&wc);

    int exitCode = 0;
    if (StartCaptureMode()) {
        MSG msg;
        while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        exitCode = static_cast<int>(msg.wParam);
    } else {
        exitCode = 1;
    }

    g_image.Destroy();
    g_screen.Destroy();
    g_dark.Destroy();
    if (SUCCEEDED(hrCo)) CoUninitialize();
    return exitCode;
}
