// 通过多条 Android 网络检测路径伪装“当前没有 VPN”，用于绕过常见的 VPN 检测逻辑。
// 同时从网卡名、旧版 ConnectivityManager、新版 NetworkCapabilities 三条路径把“VPN”伪装成不存在
function bypassVPNDetect() {
    Java.perform(function() {
        var NetworkInterface = Java.use("java.net.NetworkInterface")

        // 旧式检测路径：遍历网络接口名，常见 VPN 网卡名会包含 tun0 / ppp0。
        NetworkInterface.getAll.implementation = function() {
            var nis = this.getAll()
            console.log("call getAll function !!!")
            nis.forEach(function(ni) {
                // 当检测到接口名或显示名里包含 tun0 / ppp0 时，就把它改成 xxxx
                if (ni.name.value.indexOf("tun0") >= 0 || ni.name.value.indexOf("ppp0") >= 0 ||
                ni.displayName.value.indexOf("tun0") >= 0 || ni.displayName.value.indexOf("ppp0") >= 0) {
                    ni.name.value = "xxxx"
                    ni.displayName.value = "xxxx"
                }
            })
            return nis
        }

        // 用于在 getNetworkInfo(TYPE_VPN) 与随后 isConnected() 之间传递“本次是在查 VPN”的状态。
        var can_hook = false
        var ConnectivityManager = Java.use("android.net.ConnectivityManager");
        // 兼容旧版 Android 检测方式：直接查询 TYPE_VPN(17) 的 NetworkInfo。
        ConnectivityManager.getNetworkInfo.overload('int').implementation = function() {
            if (arguments[0] == 17) {
                can_hook = true
            }
            var ret = this.getNetworkInfo(arguments[0])
            return ret
        }
        var NetworkInfo = Java.use("android.net.NetworkInfo")
        // 如果刚刚查询的是 TYPE_VPN，就把连接状态强制改成 false。
        NetworkInfo.isConnected.implementation = function() {
            let ret = this.isConnected()
            if (can_hook) {
                ret = false
                can_hook = false
                console.log("call isConnected function !!!")
            }
            return ret
        }


        var NetworkCapabilities = Java.use("android.net.NetworkCapabilities")
        // 新版 Android 检测路径：TRANSPORT_VPN 的常量值通常是 4，这里直接伪装成不具备 VPN 传输能力。
        NetworkCapabilities.hasTransport.implementation = function() {
            var ret = this.hasTransport(arguments[0])
            if (arguments[0] == 4) {
                console.log("call hasTransport function !!!")
                ret = false
            }
            return ret
        }
        // 如果调用方进一步把 transport 名称转成人类可读字符串，则把 VPN 改成 WIFI。
        NetworkCapabilities.transportNameOf.overload('int').implementation = function() {
            var ret = this.transportNameOf(arguments[0])
            if (ret.indexOf("VPN") >= 0) {
                ret = "WIFI"
            }
            return ret;
        }
    })
}

// 脚本加载后立即启用 VPN 检测绕过逻辑。
setImmediate(bypassVPNDetect)
