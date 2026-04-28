// 创建目录，供文件写入类 RPC 复用。
function mkdirs(dirpath) {
    var FileClz = Java.use("java.io.File");
    var file = FileClz.$new(dirpath);
    if (!file.exists()) {
        file.mkdirs();
    }
}

// 将 Python 侧传入的 base64 文本还原并写入应用侧文件。
function writeFileAsBase64Content(filepath, base64) {
    try {
        var FileUtilsClz = Java.use("android.os.FileUtils");
        var StringClz = Java.use('java.lang.String');
        var Base64Clz = Java.use("android.util.Base64");
        var ByteArrayInputStreamClz = Java.use("java.io.ByteArrayInputStream");
        var FileOutputStreamClz = Java.use("java.io.FileOutputStream");
        var FileClz = Java.use("java.io.File");
        var distFilepath = FileClz.$new(filepath);
        mkdirs(distFilepath.getParent());
        var javaBase64String = StringClz.$new(base64);
        var getBytesMehtod = StringClz.getBytes.overload('java.lang.String');
        var bytes = getBytesMehtod.call(javaBase64String, 'UTF-8');
        var decodeMethod = Base64Clz.decode.overload('[B', 'int');
        var originalBinary = decodeMethod.call(Base64Clz, bytes, 0);
        var bais = ByteArrayInputStreamClz.$new(originalBinary);
        if (FileUtilsClz.copy) {
            var copyMehtod = FileUtilsClz.copy.overload('java.io.InputStream', 'java.io.OutputStream');
            var fos = FileOutputStreamClz.$new(distFilepath);
            copyMehtod.call(FileUtilsClz, bais, fos);
        } else if (FileUtilsClz.copyToFile) {
            var copyMehtod = FileUtilsClz.copyToFile.overload('java.io.InputStream', 'java.io.File');
            copyMehtod.call(FileUtilsClz, bais, distFilepath);
        }
    } catch(err) {
        console.warn(err);
    }
};

// 以“是否存在且大小匹配”的方式检查文件完整性。
function checkFile(filepath, checkLength) {
    var FileClz = Java.use("java.io.File");
    var file = FileClz.$new(filepath);
    return file.exists() && file.length() == checkLength;
};


// 借助 radar.dex 提供的 ClassRadar 获取类的结构化元数据。
function discoverClass(className) {
    if (!className) {
        return;
    }
    var radarClz = Java.use("gz.radar.ClassRadar");
    var radarClassResult = radarClz.discoverClass(className);
    return radarClassResult;
};

// 根据单个方法的雷达元数据，拼出对应的 Frida overload hook 代码。
// 进一步说明这里生成的方法 hook 结构：
// - "handle" 对实例方法是 this，对静态方法是类包装对象；
// - executor 会被记录下来，供后续 beat 打印区分调用主体；
// - 默认一定会调用原始方法，因此生成出的脚本默认是“观测型”的；
// - 非 void 方法会完整保留原始返回值。
function generateFridaMethodOverload(clzVarName, radarMethod) {
    var overloadJs = "";
    if (!radarMethod.isLocal.value || radarMethod.methodName.value.indexOf("-") > -1) {
        return overloadJs;
    }
    var methodVarName = clzVarName + "_method_" + radarMethod.methodName.value + "_" + Math.random().toString(36).slice( - 4);
    overloadJs += "var " + methodVarName + "=" + clzVarName + "." + radarMethod.methodName.value + ".overload(";
    if (radarMethod.paramsNum.value > 0) {
        for (var j = 0; j < radarMethod.paramsNum.value; j++) {
            overloadJs += "'";
            overloadJs += radarMethod.paramsClasses.value[j];
            overloadJs += "'";
            if (j < (radarMethod.paramsNum.value - 1)) {
                overloadJs += ",";
            }
        }
    }
    overloadJs += ");";
    overloadJs += methodVarName;
    overloadJs += ".implementation = function(";
    var paramsJs = "";
    for (var j = 0; j < radarMethod.paramsNum.value; j++) {
        paramsJs += radarMethod.parameterNames.value[j];
        if (j < (radarMethod.paramsNum.value - 1)) {
            paramsJs += ",";
        }
    }
    overloadJs += paramsJs;
    overloadJs += ") {";
    var handle = "this";
    if (radarMethod.isStatic.value) {
        handle = clzVarName;
    }
    if (handle == "this") {
        overloadJs += "var executor = this.hashCode();";
    } else {
        overloadJs += "var executor = 'Class';";
    }
    overloadJs += "var beatText = '" + radarMethod.describe.value + "';";
    overloadJs += "var beat = newMethodBeat(beatText, executor);";
    if (radarMethod.returnClass.value != "void") {
        overloadJs += "var ret = ";
    }
    overloadJs += methodVarName + ".call(" + handle;
    if (radarMethod.paramsNum.value > 0) {
        overloadJs += "," + paramsJs + ");";
    } else {
        overloadJs += ");";
    }
	overloadJs += "printBeat(beat);";
    if (radarMethod.returnClass.value != "void") {
        overloadJs += "return ret;";
    }
    overloadJs += "};";
    return overloadJs;
}

//生成构造方法的overload
// 根据构造方法元数据，生成 $init.overload(...) 的 hook 代码。
// 进一步说明构造函数 hook 的生成方式：
// - 在 Frida 的 Java API 中，构造函数统一用 $init 表示；
// - 参数名在这里本地合成成 v0、v1 这类临时变量；
// - 返回值必须是真实构造出的对象，这样不会破坏原始应用行为。
function generateFridaConstructorMethodOverload(clzVarName, constructorMethod) {
    var overloadJs = "";
    if (!constructorMethod.isLocal.value) {
        return overloadJs;
    }
    var constructorMethodVarName = clzVarName + "_init_" + Math.random().toString(36).slice( - 4);
    var hookConstructorMethodJs = clzVarName + ".$init.overload(";
    if (constructorMethod.paramsNum.value > 0) {
        for (var j = 0; j < constructorMethod.paramsNum.value; j++) {
            hookConstructorMethodJs += "'";
            hookConstructorMethodJs += constructorMethod.params.value[j];
            hookConstructorMethodJs += "'";
            if (j < (constructorMethod.paramsNum.value - 1)) {
                hookConstructorMethodJs += ",";
            }
        }
    }
    hookConstructorMethodJs += ");";
    overloadJs += "var " + constructorMethodVarName + " = " + hookConstructorMethodJs;
    overloadJs += constructorMethodVarName + ".implementation = function(";
    var paramsJs = "";
    for (var j = 0; j < constructorMethod.paramsNum.value; j++) {
        paramsJs += "v" + j;
        if (j < (constructorMethod.paramsNum.value - 1)) {
            paramsJs += ",";
        }
    }
    overloadJs += paramsJs;
    overloadJs += ") {";
    overloadJs += "var executor = this.hashCode();";
    overloadJs += "var beatText = '" + constructorMethod.describe.value + "';";
    overloadJs += "var beat = newMethodBeat(beatText, executor);";
    overloadJs += "var returnObj = ";
    overloadJs += constructorMethodVarName + ".call(this";
    if (constructorMethod.paramsNum.value > 0) {
        overloadJs += "," + paramsJs + ");";
    } else {
        overloadJs += ");";
    }
    overloadJs += "printBeat(beat);";
    overloadJs += "return returnObj;};";
    return overloadJs;
}

// 把 Python 侧传来的方法选择器拆成“方法名 + 参数列表”的结构。
// 支持：
// - "*"：hook 全部普通方法和构造
// - "_"：hook 全部构造方法
// - "c"：按方法名匹配所有同名重载
// - "c(java.lang.String)"：只匹配一个精确重载
// - "_(android.os.Bundle)"：只匹配一个精确构造重载
function parseMethodSelector(methodSelector) {
    var selector = (methodSelector || "").trim();
    var parsed = {
        raw: selector,
        hookAllMethods: selector == "?" || selector == "*",
        hookAllConstructors: selector == "_" || selector == "*",
        isConstructor: false,
        exactSignature: false,
        methodName: selector,
        params: []
    };
    var leftParenIndex = selector.indexOf("(");
    var rightParenIndex = selector.lastIndexOf(")");
    if (leftParenIndex > -1 && rightParenIndex > leftParenIndex) {
        parsed.exactSignature = true;
        parsed.methodName = selector.substring(0, leftParenIndex).trim();
        parsed.isConstructor = parsed.methodName == "_";
        var paramsPart = selector.substring(leftParenIndex + 1, rightParenIndex).trim();
        if (paramsPart.length > 0) {
            parsed.params = paramsPart.split(",").map(function(item) {
                return item.trim();
            });
        }
    } else {
        parsed.isConstructor = selector == "_";
    }
    return parsed;
}

// 判断方法参数列表是否与选择器里的精确签名完全一致。
function paramsExactlyMatch(radarMethod, selectorParams) {
    var methodParams = radarMethod.paramsClasses.value || [];
    if (methodParams.length != selectorParams.length) {
        return false;
    }
    for (var i = 0; i < methodParams.length; i++) {
        if ((methodParams[i] + "").trim() != selectorParams[i]) {
            return false;
        }
    }
    return true;
}

// 判断普通方法是否应该被当前选择器命中。
function shouldHookNormalMethod(radarMethod, methodSelector) {
    if (methodSelector.hookAllMethods) {
        return true;
    }
    if (methodSelector.isConstructor) {
        return false;
    }
    if (!methodSelector.exactSignature) {
        return radarMethod.matchName(methodSelector.methodName);
    }
    return radarMethod.matchName(methodSelector.methodName) && paramsExactlyMatch(radarMethod, methodSelector.params);
}

// 判断构造方法是否应该被当前选择器命中。
function shouldHookConstructorMethod(constructorMethod, methodSelector) {
    if (methodSelector.hookAllConstructors) {
        return true;
    }
    if (!methodSelector.isConstructor || !methodSelector.exactSignature) {
        return false;
    }
    return paramsExactlyMatch(constructorMethod, methodSelector.params);
}

//RadarClassResult  string
// 将一个类的雷达信息转换成可以直接保存到文件中的 hook 脚本片段。
// methodName 为 "*" 时同时 hook 普通方法和构造；"_" 仅表示构造方法。
// 这个辅助函数有意只返回源码片段，而不直接触发 Java.use() 之后的执行副作用。
// 这样可以把“在运行时里生成脚本”和“后续真正执行脚本”明确分开：
// - 生成阶段：通过 RPC 在目标 App 里读取类信息并拼出源码；
// - 执行阶段：由 Python 把源码保存成文件，再走普通 attach/spawn 流程。
function generateMethodHookJs(radarClassResult, methodName) {
    if (radarClassResult.isEnum.value || radarClassResult.isInterface.value) {
        return "";
    }
    var hookJs = "";
    var hasHook = false;
    var clzHookJs = "";
    var methodSelector = parseMethodSelector(methodName);

    var clzVarName = radarClassResult.className.value.replace(/[\.$;]/g, "_") + "_clz";
    clzHookJs += "var " + clzVarName + " = Java.use('" + radarClassResult.className.value + "');";
    var methods = radarClassResult.methods.value;
    for (var i = 0; i < methods.length; i++) {
        var radarMethod = methods[i];
        if (shouldHookNormalMethod(radarMethod, methodSelector)) {
            hasHook = true;
            clzHookJs += generateFridaMethodOverload(clzVarName, radarMethod);
        }
    }

    //是否需要hook构造方法
    var constructorMethods = radarClassResult.constructorMethods.value;
    for (var i = 0; i < constructorMethods.length; i++) {
        if (shouldHookConstructorMethod(constructorMethods[i], methodSelector)) {
            hasHook = true;
            clzHookJs += generateFridaConstructorMethodOverload(clzVarName, constructorMethods[i]);
        }
    }

    if (hasHook) {
        hookJs += clzHookJs;
    }
    return hookJs;
};

// 轻量探测类是否可被 Java.use 正常解析。
function class_exists(className) {
    var exists = false;
    try {
        var clz = Java.use(className);
        exists = true;
    } catch(err) {
        //console.log(err);
    }
    return exists;
};

//可能会超时 为了防止这个发生，可以在函数 setImmediate 中给你的脚本添加一层包装
// 这一段就是 rpc.js 暴露给 Python 的服务接口总表。
// - Python 会先把本文件注入到目标进程；
// - 然后通过 script.exports_sync.xxx(...) 调用下面这些方法；
// - 真正执行这些方法的位置，不在本机 Python，而在目标 App 自己的运行时里；
// - 所以这里既能查 Activity/View/对象，也能借助运行时元数据生成 hook 脚本。
rpc.exports = {
    // 启动内嵌 HTTP 服务。
    // 传入 dex_file 时，会组合 radar.dex 与外部 dex，并按类名单启动扫描模式。
    // 在目标 App 进程内启动嵌入式 HTTP 服务。
    // 传入 dex_file 时：
    // - 会创建一个同时串联 radar.dex 与外部 dex 的 DexClassLoader；
    // - 把 Java.classFactory.loader 切到这个新的 loader；
    // - 再把 Python 传来的类名 CSV 转成 Java ArrayList；
    // - 最后调用 HookerWebServerBoot.scanAndStartHttpServer(...)。
    // 不传 dex_file 时：
    // - 只加载 radar.dex；
    // - 启动默认的内置 HTTP 服务。
    starthttpserver: function (dex_file, allClz) {
        var result = "";
        Java.perform(function() {
            if (dex_file) {
                var DexClassLoader = Java.use("dalvik.system.DexClassLoader");
                var ActivityThread = Java.use("android.app.ActivityThread");
                var app = ActivityThread.currentApplication();
                var context = app.getApplicationContext();
                var cacheDir = context.getCodeCacheDir().getAbsolutePath();
                var parent = context.getClassLoader();
                var dexPath = "/data/local/tmp/radar.dex:" + dex_file;
                var newLoader = DexClassLoader.$new(
                    dexPath,
                    cacheDir,
                    null,
                    parent
                );
                Java.classFactory.loader = newLoader;
                var httpServerBoot = Java.use('gz.httpserver.HookerWebServerBoot');
                var ArrayList = Java.use("java.util.ArrayList");
                // JS 里分割
                var arr = allClz.split(",");
                // 创建 ArrayList
                var clzList = ArrayList.$new();
                // 填充 ArrayList<String>
                for (var i = 0; i < arr.length; i++) {
                    clzList.add(arr[i]);
                }
                result = httpServerBoot.scanAndStartHttpServer(clzList);
            }else{
                Java.openClassFile("/data/local/tmp/radar.dex").load();
                var httpServerBoot2 = Java.use('gz.httpserver.HookerWebServerBoot');
                result = httpServerBoot2.startDefaultHttpServer();
            }
        });
        return result;
    },
    // 按需加载 radar.dex，保证 ClassRadar / Android / ObjectsStore 等类可用。
    // 确保 radar.dex 已经加载到当前进程。
    // 绝大多数高层 RPC 都依赖这些类：
    // - gz.radar.ClassRadar
    // - gz.radar.Android
    // - gz.radar.objects.ObjectsStore
    // 这个函数可以重复调用，已经加载过时不会产生额外副作用。
    loadradardex: function() {
        Java.perform(function() {
            if (!class_exists("gz.radar.ClassRadar")) {
                var context = Java.use("android.app.ActivityThread").currentApplication().getApplicationContext();
                var packageName = context.getPackageName();
                Java.openClassFile('/data/local/tmp/radar.dex').load();
            }
        });
    },
    // 判断指定类是否存在。
    // 轻量判断某个类名是否存在。
    // Python 通常会先调这个接口，再决定是否继续生成该类的 hook 脚本。
    containsclass: function(className) {
        var result = false;
        Java.perform(function() {
            result = class_exists(className);
        });
        return result;
    },
    // 自动生成指定类/方法的 hook 脚本文本，返回给 Python 侧保存。
    // 生成一份完整的 Frida hook 脚本文本。
    // 这里做的不是“直接执行 hook”，而是借助目标 App 的运行时信息生成源码，
    // 再把源码返回给 Python 去保存到工作目录。
    // 整体流程是：
    // 1. Python 传入 className 和方法选择器；
    // 2. rpc.js 通过 radar.dex 获取类元数据；
    // 3. 调用上面的辅助生成函数拼出 Java.perform(function() { ... })；
    // 4. Python 接收返回文本并写成新的 .js 文件。
    hookjs: function(className, toSpace) {
        var found = true;
        var hookJs = "Java.perform(function() {\n";
        var className = className;
        var methodName = toSpace;
        Java.perform(function() {
            var radarClassResult = discoverClass(className);
            if (radarClassResult) {
                hookJs += generateMethodHookJs(radarClassResult, methodName);
                hookJs += "});";
            } else {
                found = false;
                console.error("Not found class " + className);
            }
        });
        if (found) {
            return hookJs;
        }
        return "";
    },
    // 将 base64 内容远程写入目标进程可访问的文件路径。
    // 远程写文件原语，用来把内容放进目标进程可访问的路径里。
    // 使用 base64 是为了让 Python 与 Frida 之间的传输保持文本安全。
    write: function(filename, contentAsBase64) {
        Java.perform(function() {
            //console.log(contentAsBase64);
            writeFileAsBase64Content(filename, contentAsBase64);
        });
    },
    // 校验目标文件是否存在且大小符合预期。
    // 远程文件校验原语，用来确认设备侧文件是否准备完成。
    checkfile: function(filename, filelength) {
        var ret = false;
        Java.perform(function() {
            ret = checkFile(filename, filelength);
        });
        return ret;
    },
    // 获取当前进程中 Activity 的结构化信息报告。
    // 生成 Activity 报告文本。
    // CLI 会直接打印这份字符串，因此这里返回格式化文本比返回复杂结构更直接。
    activitys: function() {
        var report = "";
        Java.perform(function() {
            try {
                var radarAndroidClz = Java.use("gz.radar.Android");
                var activityInfos = radarAndroidClz.getActivityInfos();
                report += ("Found Activities: " + activityInfos.length) + "\n";
                for (var i = 0; i < activityInfos.length; i++) {
                    try {
                        report += ("------------------" + (i) + "--------------------") + "\n";
                        var activityInfo = activityInfos[i];
                        report += ("Activity Title: " + activityInfo.getTitle()) + "\n";
                        report += ("Activity Class: " + activityInfo.getClazz()) + "\n";
                        report += ("Activity SuperClass: " + activityInfo.getSuperClazz()) + "\n";
                        report += ("Activity ImplementInterfaces: " + activityInfo.getImplementInterfaces()) + "\n";
                        report += ("Activity OnTop: " + activityInfo.isOnTop()) + "\n";
                        report += ("Activity Paused: " + activityInfo.isPaused()) + "\n";
                        report += ("Activity Stopped: " + activityInfo.isStopped()) + "\n";
                        var androidApkFields = activityInfo.getAndroidApkFields();
                        report += ("Activity Fields: " + androidApkFields.length) + "\n";
                        for (var j = 0; j < androidApkFields.length; j++) {
                            report += ("\t" + androidApkFields[j].toLine()) + "\n";
                        }
                        var methods = activityInfo.methods();
                        report += ("Activity Methods: " + methods.length) + "\n";
                        for (var j = 0; j < methods.length; j++) {
                            report += ("\t" + methods[j]) + "\n";
                        }
                    } catch(err) {
                        console.log(err);
                    }
                }
            } catch(err) {
                console.log(err);
            }

        });
        return report;
    },
    // 获取当前进程中 Service 的结构化信息报告。
    // 生成 Service 报告文本。
    services: function() {
        var report = "";
        Java.perform(function() {
            var radarAndroidClz = Java.use("gz.radar.Android");
            var serviceInfos = radarAndroidClz.getServiceInfos();
            report += "Found Services: " + serviceInfos.length + "\n";
            for (var i = 0; i < serviceInfos.length; i++) {
                report += ("------------------" + (i) + "--------------------") + "\n";
                var serviceInfo = serviceInfos[i];
                report += ("Service Class: " + serviceInfo.getName()) + "\n";
                report += ("Service SuperClass: " + serviceInfo.getSuperClazz()) + "\n";
                report += ("Service ImplementInterfaces: " + serviceInfo.getImplementInterfaces()) + "\n";
                var androidApkFields = serviceInfo.getAndroidApkFields();
                report += ("Service Fields: " + androidApkFields.length) + "\n";
                for (var j = 0; j < androidApkFields.length; j++) {
                    report += ("\t" + androidApkFields[j].toLine()) + "\n";
                }
                var methods = serviceInfo.methods();
                report += ("Service Methods: " + methods.length) + "\n";
                for (var j = 0; j < methods.length; j++) {
                    report += ("\t" + methods[j]) + "\n";
                }
            }
        });
        return report;
    },
    // objectId 既支持“类名”，也支持已缓存对象的 object_id。
    // 传类名时会用 Java.choose 搜索实例；传 object_id 时则直接读取对象详情。
    // 这个接口支持两种对象探索模式。
    //
    // 模式一：传入值其实是类名。
    // - 用 Java.choose 枚举当前进程中的活跃实例；
    // - 把实例写入 ObjectsStore；
    // - 再把生成出的 object_id 打印出来，供后续继续分析。
    //
    // 模式二：传入值是之前已经保存过的 object_id。
    // - 直接读取这个对象的结构化信息；
    // - 返回字段、方法、接口等文本报告。
    objectinfo: function(objectId) {
        var report = "";
		if (class_exists(objectId)) {
			//判断是否是类名
            // Avoid collecting too many instances in a single search.
			var max = 10;
			var found = [];
			var class_name = objectId;
			Java.perform(function () {
				var ObjectsStore = Java.use("gz.radar.objects.ObjectsStore");
			    Java.choose(class_name, {
			        onMatch: function (instance) {
						if (found.length >= max) {
			                // 已达上限，直接忽略后续回调
                            // 控制单次搜索规模，避免交互式 CLI 被大量对象结果淹没。
							console.warn("The upper limit has been reached.");
			                return;
			            }
						found.push(class_name);
						var newObjectId = ObjectsStore.storeObject(instance);
						console.log("Found " + class_name + " instance: " + instance + " ObjectId: " + newObjectId);
			        },
			        onComplete: function () {
			            console.log("Search complete. Please continue exploring using object with [ObjectId]");
			        }
			    });
			});
		}else{
			//不是类名就是object_id
            // 不是类名时，就把输入当成一个已保存的 object_id。
			Java.perform(function() {
	            var radarAndroidClz = Java.use("gz.radar.Android");
	            var objectInfo = radarAndroidClz.getObjectInfo(objectId);
	            if (!objectInfo) {
	                report += "Not Found Any Object."
	                return;
	            }
	            report += ("------------------Object--------------------") + "\n";
	            report += ("Object Class: " + objectInfo.getName()) + "\n";
	            report += ("Object SuperClass: " + objectInfo.getSuperClazz()) + "\n";
	            report += ("Object ImplementInterfaces: " + objectInfo.getImplementInterfaces()) + "\n";
	            var androidApkFields = objectInfo.getAndroidApkFields();
	            report += ("Object Fields: " + androidApkFields.length) + "\n";
	            for (var j = 0; j < androidApkFields.length; j++) {
	                report += ("\t" + androidApkFields[j].toLine()) + "\n";
	            }
	            var methods = objectInfo.methods();
	            report += ("Object Methods: " + methods.length) + "\n";
	            for (var j = 0; j < methods.length; j++) {
	                report += ("\t" + methods[j]) + "\n";
	            }
	        });
		}
        return report;
    },
    // 对已有 object_id 做进一步解释，返回与其相关联的可继续探索对象。
    // 从一个已有 object_id 继续展开关联对象。
    // 适合做“顺着引用关系一路往外追”的交互式分析。
    objecttoexplain: function(objectId) {
        var report = "";
        Java.perform(function() {
            var radarAndroidClz = Java.use("gz.radar.Android");
            var explainObjs = radarAndroidClz.object2Explain(objectId);
            if (explainObjs == null) {
                report += "Not Found Any Object.";
                return;
            }
            if (explainObjs.isEmpty()) {
                report += "Cannot Explain the Object " + objectId+".";
                return;
            }
            report += "Found Objects: " + explainObjs.size() + "\n";
            for (var i = 0; i < explainObjs.size(); i++) {
                var key = explainObjs.getKey(i);
                var _objectId = explainObjs.getObjectId(i);
                report += ("------------------[" + key + "]--------------------") + "\n";
                report += ("Object Class: " + explainObjs.getObjectClass(i)) + "\n";
                report += ("Object Id:" + _objectId) + "\n";
            }
        });
        return report;
    },
    // 获取指定 View 的属性、字段和方法信息。
    // 查询一个 View，并返回包含 id、可见性、文本、字段和方法的报告。
    // 适合做偏 UI 方向的逆向分析。
    viewinfo: function(viewId) {
        var report = "";
        Java.perform(function() {
            var radarAndroidClz = Java.use("gz.radar.Android");
            var viewInfo = radarAndroidClz.getViewInfo(viewId + "");
            if (!viewInfo) {
                report += "Not Found Any Views."
                return;
            }
            report += ("------------------View--------------------") + "\n";
            report += ("View Id: " + viewInfo.getViewId()) + "\n";
            report += ("View IdName: " + viewInfo.getViewIdName()) + "\n";
            report += ("View Text: " + viewInfo.getViewText()) + "\n";
            report += ("View Visible: " + viewInfo.isVisible()) + "\n";
            report += ("View Class: " + viewInfo.getName()) + "\n";
            report += ("View SuperClass: " + viewInfo.getSuperClazz()) + "\n";
            report += ("View ImplementInterfaces: " + viewInfo.getImplementInterfaces()) + "\n";
            var androidApkFields = viewInfo.getAndroidApkFields();
            report += ("View Fields: " + androidApkFields.length) + "\n";
            for (var j = 0; j < androidApkFields.length; j++) {
                report += ("\t" + androidApkFields[j].toLine()) + "\n";
            }
            var methods = viewInfo.methods();
            report += ("View Methods: " + methods.length) + "\n";
            for (var j = 0; j < methods.length; j++) {
                report += ("\t" + methods[j]) + "\n";
            }
        });
        return report;
    },
    // 获取当前应用版本名。
    // 轻量元数据接口：返回当前应用版本名。
    appversion: function() {
        var versionName = "";
        Java.perform(function() {
            var radarAndroidClz = Java.use("gz.radar.Android");
            versionName = radarAndroidClz.getVersionName();
        });
        return versionName;
    },
    // 获取当前应用主 Activity。
    // 轻量元数据接口：返回应用声明的主 Activity。
    mainactivity: function() {
        var mainactivityName = "";
        Java.perform(function() {
            var radarAndroidClz = Java.use("gz.radar.Android");
            mainactivityName = radarAndroidClz.getMainActivity();
        });
        return mainactivityName;
    },
    // 清理脚本注入后残留的 hook / stalker 状态，供 Python detach() 统一调用。
    // Python 在卸载脚本前会调用这里做一次尽力清理。
    // 目的是清掉全局 hook / 跟踪状态，避免泄漏到下一次 attach/spawn 会话里。
	cleanup: function () {
        // 清理所有拦截器
        Interceptor.detachAll();
        // 如果你设置了定时器或 Stalker，也可以清理
        Stalker.unfollow();
        // clearInterval(...);
    }
};

// 脚本加载后立即确保 radar.dex 已经注入。
// 整个 RPC 层的类发现、对象分析、View/Activity/Service 查询都依赖它。
// 脚本加载后的自举步骤：
// rpc.js 假设 radar.dex 相关类会被尽早用到，所以在加载完成后立刻做一次检查和注入。
// 这样 Python 侧的 attach_rpc() 会更简单，通常不需要在每次 RPC 前先手动调一次 loadradardex()。
Java.perform(function() {
    if (!class_exists("gz.radar.ClassRadar")) {
        var context = Java.use("android.app.ActivityThread").currentApplication().getApplicationContext();
        var packageName = context.getPackageName();
        Java.openClassFile('/data/local/tmp/radar.dex').load();
    }
});
