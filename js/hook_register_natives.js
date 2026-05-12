// 在 Android 运行时里拦截 JNI 的 RegisterNatives 调用，
// 把“某个 Java 类动态注册了哪些 native 方法、这些 native 方法对应哪个 so 里的哪个函数地址”全部打印出来
// 使用 spawn 模式启动
// 推荐命令：spawn hook_register_natives.js


// hook libart 中的 RegisterNatives，用于监控 JNI 动态注册过程。
function hook_RegisterNatives() {
    var symbols = Module.enumerateSymbolsSync("libart.so");
    var addrRegisterNativesList = [];

    // 在 libart 导出符号中查找真正的 RegisterNatives 实现，排除 CheckJNI 版本。
    for (var i = 0; i < symbols.length; i++) {
        var symbol = symbols[i];

        //_ZN3art3JNI15RegisterNativesEP7_JNIEnvP7_jclassPK15JNINativeMethodi
        if (symbol.name.indexOf("art") >= 0 &&
                symbol.name.indexOf("JNI") >= 0 &&
                symbol.name.indexOf("RegisterNatives") >= 0 &&
                symbol.name.indexOf("CheckJNI") < 0) {
            addrRegisterNativesList.push({
                address: symbol.address,
                name: symbol.name
            });
            console.log("RegisterNatives is at ", symbol.address, symbol.name);
        }
    }

    if (addrRegisterNativesList.length > 0) {
        addrRegisterNativesList.forEach(function (item) {
            Interceptor.attach(item.address, {
                onEnter: function (args) {
                    console.log("[RegisterNatives] method_count:", args[3]);
                    var java_class = args[1];

                    // 将 jclass 转成可读的 Java 类名，便于定位是哪一个类在注册 native 方法。
                    var class_name = "<unknown>";
                    try {
                        var jniEnv = Java.vm.tryGetEnv();
                        if (jniEnv) {
                            class_name = jniEnv.getClassName(java_class);
                        }
                    } catch (e) {
                        console.log("[RegisterNatives] resolve class name failed:", e);
                    }

                    //console.log(class_name);

                    // args[2] 指向 JNINativeMethod 数组，每个元素包含 name / sig / fnPtr 三个指针。
                    var methods_ptr = ptr(args[2]);

                    var method_count = parseInt(args[3]);
                    for (var i = 0; i < method_count; i++) {
                        var name_ptr = Memory.readPointer(methods_ptr.add(i * Process.pointerSize * 3));
                        var sig_ptr = Memory.readPointer(methods_ptr.add(i * Process.pointerSize * 3 + Process.pointerSize));
                        var fnPtr_ptr = Memory.readPointer(methods_ptr.add(i * Process.pointerSize * 3 + Process.pointerSize * 2));

                        var name = Memory.readCString(name_ptr);
                        var sig = Memory.readCString(sig_ptr);

                        // 根据函数地址反查所属 so，输出 so 名、基址和偏移，便于后续静态分析。
                        var find_module = Process.findModuleByAddress(fnPtr_ptr);
                        if (find_module) {
                            console.log("[RegisterNatives] java_class:", class_name, "name:", name, "sig:", sig, "fnPtr:", fnPtr_ptr, "module_name:", find_module.name, "module_base:", find_module.base, "offset:", ptr(fnPtr_ptr).sub(find_module.base));
                        } else {
                            console.log("[RegisterNatives] java_class:", class_name, "name:", name, "sig:", sig, "fnPtr:", fnPtr_ptr, "module_name:<unknown>");
                        }

                    }
                }
            });
        });
    }
}

// 脚本加载后立即开始 hook，尽量赶在 native 动态注册发生前挂上。
setImmediate(hook_RegisterNatives);
