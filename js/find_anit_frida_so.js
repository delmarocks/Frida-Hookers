// 监控 android_dlopen_ext，记录进程运行时动态加载的 so 路径。
// 这个脚本本身不直接判断“哪个 so 一定是反 Frida”，
// 而是通过观察 so 加载时机，帮助人工定位可疑模块。

function hook_dlopen() {
    // Android 8.0 以后，很多 so 的加载都会走 android_dlopen_ext。
    var android_dlopen_ext = null;
    if (typeof Module !== "undefined" && typeof Module.findGlobalExportByName === "function") {
        android_dlopen_ext = Module.findGlobalExportByName("android_dlopen_ext");
    } else if (typeof Module !== "undefined" && typeof Module.findExportByName === "function") {
        android_dlopen_ext = Module.findExportByName(null, "android_dlopen_ext");
    }
    console.log("addr_android_dlopen_ext", android_dlopen_ext);
    if (android_dlopen_ext === null) {
        console.log("[-] 没有找到 android_dlopen_ext 导出函数");
        return;
    }

    Interceptor.attach(android_dlopen_ext, {
        onEnter: function(args) {
            var pathptr = args[0];
            if (pathptr != null && pathptr != undefined) {
                var path = ptr(pathptr).readCString();

                // 打印当前即将被加载的 so 路径，便于后续筛选可疑安全模块。
                console.log("android_dlopen_ext:", path);
            }
        },
        onLeave: function(retvel) {
            // 这里只是简单标记一次加载完成，当前未使用返回值做进一步判断。
            console.log("leave!");
        }
    })
}

// 脚本加载后立即开始监控 so 动态加载。
hook_dlopen()
