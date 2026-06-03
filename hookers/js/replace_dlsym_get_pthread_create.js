// 获取当前进程中真实的 pthread_create 导出地址
var pthread_create_ptr = Module.getExportByName(null, "pthread_create");

// 备份原始 pthread_create。
// 如果后面需要“打印参数后仍然真实创建线程”，可以调用它。
var original_pthread_create = new NativeFunction(
    pthread_create_ptr,
    'int',
    ['pointer', 'pointer', 'pointer', 'pointer']
);

// 自定义一个假的 pthread_create：
// 1. 打印线程创建参数
// 2. 解析 start_routine 落在哪个 so
// 3. 直接返回 0，伪装成“创建线程成功”
//
// 注意：当前实现不会真的创建线程。
// 适合用于“吞掉疑似检测线程”的场景。
var my_pthread_create = new NativeCallback(function (thread_ptr, attr_ptr, start_routine, arg_ptr) {
    console.log("[*] 自定义 pthread_create 被调用！");
    console.log("    thread_ptr:     " + thread_ptr);
    console.log("    attr_ptr:       " + attr_ptr);
    console.log("    start_routine:  " + start_routine);
    console.log("    arg_ptr:        " + arg_ptr);

    // 根据线程入口地址反查所属模块
    var find_module = Process.findModuleByAddress(start_routine);
    if (find_module) {
        console.log(
            "这是 pthread_create 传入的函数地址，可继续去 hook 该函数看 BLR X8 的位置，再决定是否 NOP -> Module: "
            + find_module.name
            + " offset:"
            + start_routine.sub(find_module.base)
        );
    } else {
        console.log("start_routine 不在已加载模块中，无法解析模块信息");
    }

    // 这里直接返回成功，但不真正创建线程
    // 调用方会误以为线程已经创建成功
    return 0;
}, 'int', ['pointer', 'pointer', 'pointer', 'pointer']);

// hook dlsym：
// 目的不是直接改 pthread_create 真身，
// 而是拦截“谁在动态解析 pthread_create”
Interceptor.attach(Module.getExportByName(null, "dlsym"), {
    onEnter(args) {
        // dlsym(handle, symbol) 的第二个参数是符号名
        this.symbol = Memory.readUtf8String(args[1]);
    },
    onLeave(retval) {
        // 只关心解析 pthread_create 的场景
        if (this.symbol.indexOf("pthread_create") !== -1) {
            console.log("[*] dlsym loaded pthread_create, addr:", retval);

            // 获取当前线程调用栈
            var backtrace = Thread.backtrace(this.context, Backtracer.ACCURATE);

            // 栈顶附近地址，近似视为当前 dlsym 调用者
            var callerAddress = backtrace[0];
            var find_module = Process.findModuleByAddress(callerAddress);

            // 只针对目标模块 libmsaoaidsec.so 生效，避免误伤其他模块
            if (find_module && find_module.name.indexOf("libmsaoaidsec.so") !== -1) {
                // console.log('\nBacktrace:\n' + Thread.backtrace(this.context, Backtracer.ACCURATE)
                //     .map(DebugSymbol.fromAddress).join('\n'));
                console.log(
                    "invoke dlsym |--> Module: "
                    + find_module.name
                    + " offset:"
                    + callerAddress.sub(find_module.base)
                );

                // 把 dlsym 返回的 pthread_create 地址替换成我们自定义的假函数地址
                // 这样目标 so 后续调到的不是 libc 里的真实 pthread_create，而是 my_pthread_create
                retval.replace(ptr(my_pthread_create));
            }
        }
    }
});

// 下面是备选思路：
// 如果目标不走 dlsym("pthread_create")，也可能继续往下落到 clone。
// 可以在 clone 层继续分析线程创建链路。

// var clone = Module.findExportByName('libc.so', 'clone');
// Interceptor.attach(clone, {
//     onEnter: function(args) {
//         // args[3] 通常和子线程栈/启动上下文相关
//         if(args[3] != 0){
//             var callerAddress = args[3].add(96).readPointer()
//             var find_module = Process.findModuleByAddress(callerAddress);
//             if (find_module && find_module.name.indexOf("libmsaoaidsec.so") !== -1) {
//                 // console.log('\nBacktrace:\n' + Thread.backtrace(this.context, Backtracer.ACCURATE)
//                 //     .map(DebugSymbol.fromAddress).join('\n'));
//                 console.log("hook_clone invoke Module: " + find_module.name + " offset:" + callerAddress.sub(find_module.base));
//                 // 理论上也可尝试改写对应参数，达到类似“替换线程创建入口”的效果
//                 args[3] = ptr(my_pthread_create);
//             }
//         }
//     },
//     onLeave: function(retval) {
//     }
// });

// // 下面是另一条备选思路：
// // hook strstr / strcmp，把 frida 相关特征字符串比较结果改成“不匹配”。
// // 适合处理基于字符串扫描的反 Frida 检测。

// function anti_check_frida_feature() {
//     var pt_strstr = Module.findExportByName("libc.so", 'strstr');
//     var pt_strcmp = Module.findExportByName("libc.so", 'strcmp');

//     Interceptor.attach(pt_strstr, {
//         onEnter: function (args) {
//             var str1 = args[0].readCString();
//             var str2 = args[1].readCString();
//             if (
//                 str2.indexOf("REJECT") !== -1 ||
//                 str2.indexOf("tmp") !== -1 ||
//                 str2.indexOf("frida") !== -1 ||
//                 str2.indexOf("gum-js-loop") !== -1 ||
//                 str2.indexOf("gmain") !== -1 ||
//                 str2.indexOf("linjector") !== -1
//             ) {
//                 //console.log("strstr-->", str1, str2);
//                 this.hook = true;
//             }
//         }, onLeave: function (retval) {
//             if (this.hook) {
//                 retval.replace(0);
//             }
//         }
//     });

//     Interceptor.attach(pt_strcmp, {
//         onEnter: function (args) {
//             var str1 = args[0].readCString();
//             var str2 = args[1].readCString();
//             if (
//                 str2.indexOf("REJECT") !== -1 ||
//                 str2.indexOf("tmp") !== -1 ||
//                 str2.indexOf("frida") !== -1 ||
//                 str2.indexOf("gum-js-loop") !== -1 ||
//                 str2.indexOf("gmain") !== -1 ||
//                 str2.indexOf("linjector") !== -1
//             ) {
//                 //console.log("strcmp-->", str1, str2);
//                 this.hook = true;
//             }
//         }, onLeave: function (retval) {
//             if (this.hook) {
//                 retval.replace(0);
//             }
//         }
//     })
// }

// setImmediate(anti_check_frida_feature)
