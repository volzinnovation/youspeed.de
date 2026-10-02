import Foundation

// OFFLINE ONLY. App targets never compile this helper. Frozen research v1.
// Raw evidence is retained even when the native detector sees top-hat input.
enum LightingRecovery {
    static var mode = "AB"
    static var counters: [String: Int] = [:]
    static func count(_ key: String) { counters[key, default: 0] += 1 }
    struct Row {
        let values, sums, squares: [Double]
        init(_ gray: [UInt8], _ width: Int, _ y: Int) {
            var v = [Double](repeating: 0, count: width)
            var s = [Double](repeating: 0, count: width+1)
            var q = s
            for x in 0..<width {
                var total = 0.0, squared = 0.0
                for dy in -1...1 {
                    let p = Double(gray[(y+dy)*width+x]); total += p; squared += p*p
                }
                v[x] = total/3; s[x+1] = s[x]+total; q[x+1] = q[x]+squared
            }
            values = v; sums = s; squares = q
        }
        func stats(_ x: Int, _ r: Int) -> (Double, Double) {
            let n = Double(3*(2*r+1))
            let mean = (sums[x+r+1]-sums[x-r])/n
            return (mean, max(0,(squares[x+r+1]-squares[x-r])/n-mean*mean))
        }
    }
    static func geometry(_ gray: [UInt8], _ width: Int, _ height: Int,
                         _ row: Row, _ x: Int, _ y: Int, _ radius: Int) -> Bool {
        // Measured opposite-polarity borders, not assumed metric stripe width.
        let reach = radius+3
        func edge(_ center: Int, _ yy: Int, _ polarity: Double) -> (Int, Double)? {
            var bestX = center, best = 0.0
            for xx in (center-2)...(center+2) {
                let g = polarity * Double(Int(gray[yy*width+xx+1])-Int(gray[yy*width+xx-1]))
                if g > best { best = g; bestX = xx }
            }
            return best >= 10 ? (bestX,best) : nil
        }
        var left = x-1, right = x+1, lg = 0.0, rg = 0.0
        for xx in (x-reach)..<x {
            let g = row.values[xx+1]-row.values[xx-1]
            if g > lg { lg=g; left=xx }
        }
        for xx in (x+1)...(x+reach) {
            let g = row.values[xx-1]-row.values[xx+1]
            if g > rg { rg=g; right=xx }
        }
        let measured = right-left
        let maxWidth = max(4,Int((4+8*Double(y)/Double(height-1))*Double(width)/384))
        guard lg >= 10, rg >= 10, measured >= 2, measured <= maxWidth else { return false }
        func slope(_ xx: Int) -> Double {
            let gx = Double(Int(gray[y*width+xx+1])-Int(gray[y*width+xx-1]))
            let gy = Double(Int(gray[(y+1)*width+xx])-Int(gray[(y-1)*width+xx]))
            return abs(gx) >= 8 ? -gy/gx : 100
        }
        let ls = slope(left), rs = slope(right)
        guard abs(ls) <= 2, abs(rs) <= 2, abs(ls-rs) <= 0.65,
              (1+ls*rs)/sqrt((1+ls*ls)*(1+rs*rs)) >= 0.80 else { return false }
        for dy in [-3,3] {
            let a = left+Int((ls*Double(dy)).rounded())
            let b = right+Int((rs*Double(dy)).rounded())
            guard a >= 3, b < width-3,
                  let le = edge(a,y+dy,1), let re = edge(b,y+dy,-1),
                  re.0 > le.0, abs(Double(re.0-le.0-measured)) <= 2.5 else { return false }
        }
        return true
    }
    static func response(_ gray: [UInt8], _ width: Int, _ height: Int, _ row: Row,
                         _ x: Int, _ y: Int, _ radii: [Int], _ check: (Int) -> Bool) -> (Double, Bool) {
        var best = 0.0
        for r in radii {
            guard check(1) else { return (0,true) }
            let (center,_) = row.stats(x,r)
            let (left,lv) = row.stats(x-3*r-1,r)
            let (right,rv) = row.stats(x+3*r+1,r)
            let contrast = min(center-left,center-right)
            // Bounded noise floor and reject dark/clipped support on ORIGINAL luma.
            guard center >= 40, center < 230, row.values[x] < 230, left >= 18, right >= 18, contrast >= 12 else { continue }
            let normalized = contrast / max(6,sqrt(max(lv,rv)))
            if mode.contains("B") && normalized < 2.5 { continue }
            if !mode.contains("B") && contrast < 26 { continue }
            count("photometricPass")
            if mode.contains("A") {
                guard check(40) else { return (0,true) }
                guard geometry(gray,width,height,row,x,y,r) else { continue }
            }
            count("qualifiedPass")
            // Continuous strength; cap recovery so normalization cannot make it arbitrarily strong.
            let score = mode.contains("B") ? min(60,max(26,normalized*10)) : min(60,contrast)
            best = max(best,score)
        }
        return (best,false)
    }
}
