// EditText 通常绑定搜索按钮或输入事件，是定位“搜索”接口实现代码的有效入口，辅助识别核心业务逻辑。
// 用于跟踪获取 EditText 的 getText() 事件，并获取其真实 Class 类型。

var EDIT_TEXT_CATEGORY = "edit-text";

function emitEvent(message, details) {
    if (typeof Hookers !== "undefined") {
        Hookers.event(EDIT_TEXT_CATEGORY, message, details);
        return;
    }
    console.log("[edit-text] " + message);
}

// 主要 hook 了三处：
// 1.TextView.setText(CharSequence)
// 2.TextView.getText()
// 3.AppCompatEditText.getText()
// EditText 继承自 TextView ；很多输入框最终都会走 TextView 的 setText() / getText()
// 但有些项目用了 androidx.appcompat.widget.AppCompatEditText，它可能有自己的 getText() 实现，所以又补了一层单独 hook

// 统一打印一次方法调用的线程、调用栈和耗时信息。
function methodInBeat(invokeId, timestamp, methodName, executor) {
    var startTime = timestamp;
    var threadClz = Java.use("java.lang.Thread");
    var currentThread = threadClz.currentThread();
    emitEvent(methodName, {
        invokeId: invokeId,
        executor: executor,
        threadId: currentThread.getId(),
        threadName: currentThread.getName(),
        usedTimeMs: new Date().getTime() - startTime
    });
};

// 根据类名获取对应的 Java Class 对象。
function makeClass(className) {
    var classClz = Java.use("java.lang.Class");
    var forNameFunc = classClz.forName.overload("java.lang.String");
    return forNameFunc.call(classClz, className);
};

// 判断对象是否属于指定父类或接口。
function isClass(obj, superClzName) {
    var objClz = obj.getClass();
    var superClz = makeClass(superClzName);
    return superClz.isAssignableFrom(objClz);
};

// 判断目标类是否存在，避免在不同依赖环境下直接 hook 失败。
function classExists(className) {
    var exists = false;
    try {
        var clz = Java.use(className);
        exists = true;
    } catch(err) {
        //console.log(err);
    }
    return exists;
};

Java.perform(function() {
    var androidLogClz = Java.use("android.util.Log");
    var exceptionClz = Java.use("java.lang.Exception");
    var textViewClz = Java.use("android.widget.TextView");
    var charSequenceClz = Java.use("java.lang.CharSequence");

    // EditText 继承自 TextView，因此直接从 TextView 的 setText(CharSequence) 入口切入。
    if (textViewClz.setText) {
        var setTextFunc = textViewClz.setText.overload("java.lang.CharSequence");
        setTextFunc.implementation = function(v0) {
            var startTime = new Date().getTime();
            setTextFunc.call(this, v0);

            // 只记录真正的 EditText，避免普通 TextView 的文本设置把日志刷满。
            if (isClass(this, "android.widget.EditText")) {
                var clz = this.getClass().getName();
                var viewId = this.getId();
                var invokeId = Math.random().toString(36).slice( - 8);
                var executor = this.hashCode();
                methodInBeat(invokeId, startTime, 'android.widget.EditText.setText()', executor);
                emitEvent("捕获到 EditText.setText()", {
                    viewClass: clz,
                    viewId: viewId,
                    text: v0 ? v0.toString() : ""
                });
            }
        };
    }

    // EditText 的 getText() 同样继承自 TextView，因此这里统一拦截读取文本的行为。
    if (textViewClz.getText) {
        var getTextFunc = textViewClz.getText.overload();
        getTextFunc.implementation = function() {
            var startTime = new Date().getTime();
            var editable = getTextFunc.call(this);
            if (isClass(this, "android.widget.EditText")) {
                var clz = this.getClass().getName();
                var viewId = this.getId();
                var invokeId = Math.random().toString(36).slice( - 8);
                var executor = this.hashCode();
                methodInBeat(invokeId, startTime, 'android.widget.EditText.getText()', executor);
                emitEvent("捕获到 EditText.getText()", {
                    viewClass: clz,
                    viewId: viewId,
                    text: Java.cast(editable, charSequenceClz).toString()
                });
            }
            return editable;
        };
    }

    // AppCompatEditText 在部分场景下有自己的 getText 实现，因此单独补一层 hook。
    if (classExists("androidx.appcompat.widget.AppCompatEditText")) {
        var appCompatEditTextClz = Java.use("androidx.appcompat.widget.AppCompatEditText");
        var appCompatEditTextClzGetTextFunc = appCompatEditTextClz.getText.overload();
        appCompatEditTextClzGetTextFunc.implementation = function() {
            var startTime = new Date().getTime();
            var editable = appCompatEditTextClzGetTextFunc.call(this);
            var clz = this.getClass().getName();
            var viewId = this.getId();
            var invokeId = Math.random().toString(36).slice( - 8);
            var executor = this.hashCode();
            methodInBeat(invokeId, startTime, 'androidx.appcompat.widget.AppCompatEditText.getText()', executor);
            emitEvent("捕获到 AppCompatEditText.getText()", {
                viewClass: clz,
                viewId: viewId,
                text: Java.cast(editable, charSequenceClz).toString()
            });
            return editable;
        };
    }
});
