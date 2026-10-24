import Foundation

/// Native top-left pixels. Detection context may cross the primary boundary;
/// the returned OCR rectangle never does. Shared semantics with Android.
struct TrafficSignPlateRect: Equatable, Sendable {
    let x: Int, y: Int, width: Int, height: Int
}

/// Pixel-derived bounded assembly inspection; no caller can assert completeness.
struct TrafficSignPlateScan: Equatable, Sendable {
    enum Status: String, Sendable { case complete, plain, unresolved }
    let status: Status
    let union: TrafficSignPlateRect?
    let components: [TrafficSignPlateRect]
    let decision: String
    var lowerMinimum: Int? = nil
    var lowerMaximum: Int? = nil
}

enum TrafficSignPlateDetector {
    static let revision = "bounded-plate-frame-v1"
    static func select(width: Int, height: Int, rgba: [UInt8]) -> TrafficSignPlateRect? {
        scan(width: width, height: height, rgba: rgba).union
    }
    static func scan(width: Int, height: Int, rgba: [UInt8]) -> TrafficSignPlateScan {
        if let detected = detect(width: width, height: height, rgba: rgba) { return detected }
        guard width >= 48, height >= 64, width * height <= 4_000_000, rgba.count == width * height * 4 else {
            return .init(status: .unresolved, union: nil, components: [], decision: "native_context_invalid")
        }
        // Absence is admitted only for a measured clear lower context. Detector
        // failure against busy/dark/partial content never means an unconditional sign.
        var low = 255, high = 0
        for y in (height / 2)..<height { for x in 0..<width {
            let i = (y * width + x) * 4
            let value = (Int(rgba[i]) + Int(rgba[i+1]) + Int(rgba[i+2])) / 3
            low = min(low, value); high = max(high, value)
        } }
        let clear = low >= 40 && high - low <= 24
        return .init(status: clear ? .plain : .unresolved, union: nil, components: [],
                     decision: clear ? "quiet_lower_context" : "ambiguous_or_incomplete_context", lowerMinimum: low, lowerMaximum: high)
    }
    private static func detect(width: Int, height: Int, rgba: [UInt8]) -> TrafficSignPlateScan? {
        guard width >= 48, height >= 64, width * height <= 4_000_000, rgba.count == width * height * 4 else { return nil }
        let half = height / 2, overlap = min(half, max(5, min(16, Int((Double(width) * 0.08).rounded()))))
        let start = half - overlap, nativeHeight = height - start
        let factor = max(1.0, Double(max(width, nativeHeight)) / 640)
        let w = max(1, Int(Double(width) / factor)), h = max(1, Int(Double(nativeHeight) / factor))
        var luminance = [Double](repeating: 0, count: w*h), neutral = [Bool](repeating: false, count: w*h)
        for y in 0..<h { for x in 0..<w {
            let sx = min(width-1, Int(Double(x)*factor)), sy = min(height-1, start+Int(Double(y)*factor))
            let i = (sy*width+sx)*4, r = Double(rgba[i]), g = Double(rgba[i+1]), b = Double(rgba[i+2]), level = (r+g+b)/3
            luminance[y*w+x] = level
            neutral[y*w+x] = max(r,g,b)-min(r,g,b) <= 65 || (b >= g && g >= r && b-r <= max(65,level*0.5))
        } }
        let brightness = luminance.sorted()[Int(Double(luminance.count)*0.9)]
        var unsafePanel = false
        for scale in [0.65, 0.60, 0.55] {
            var white = luminance.indices.map { neutral[$0] && luminance[$0] >= max(60,brightness*scale) }
            var candidates = [[Int]]()
            var panelBounds = [[Int]]()
            var bordersComplete = true
            var allPanelsReadable = true
            for seed in white.indices where white[seed] {
                white[seed] = false; var queue = [seed], head = 0
                var l = seed%w, r = l, t = seed/w, b = t, total = 0.0
                while head < queue.count {
                    let i = queue[head]; head += 1; let x=i%w, y=i/w
                    l=min(l,x);r=max(r,x);t=min(t,y);b=max(b,y);total += luminance[i]
                    for other in [x>0 ? i-1 : -1,x+1<w ? i+1 : -1,i-w,i+w] where other >= 0 && other < w*h && white[other] {
                        white[other]=false;queue.append(other)
                    }
                }
                let cw=r-l+1, ch=b-t+1
                // Even a few bottom-edge rows can be the top of a clipped
                // second plate. Readability thresholds must not erase it.
                if b == h-1, ch >= 2, ch < 12, Double(cw) >= 0.4*Double(w),
                   abs(Double(l+r+1)/2-Double(w)/2) <= 0.25*Double(w) { unsafePanel = true }
                guard Double(cw) >= 0.4*Double(w), ch >= 12, (1.2...8).contains(Double(cw)/Double(ch)),
                      Double(queue.count) >= 0.6*Double(cw*ch), abs(Double(l+r+1)/2-Double(w)/2) <= 0.25*Double(w) else { continue }
                let margin=max(2,min(5,Int((Double(min(cw,ch))*0.08).rounded()))), paper=total/Double(queue.count)
                var rowsL=[Int](repeating:w,count:h), rowsR=[Int](repeating:-1,count:h)
                var colsT=[Int](repeating:h,count:w), colsB=[Int](repeating:-1,count:w)
                for i in queue { let x=i%w,y=i/w;rowsL[y]=min(rowsL[y],x);rowsR[y]=max(rowsR[y],x);colsT[x]=min(colsT[x],y);colsB[x]=max(colsB[x],y) }
                let trimX=max(1,Int((Double(cw)*0.12).rounded())), trimY=max(1,Int((Double(ch)*0.12).rounded()))
                var profiles=[[(Int,Int)]](repeating:[],count:4)
                for x in (l+trimX)..<(r+1-trimX) where colsB[x] >= 0 {profiles[0].append((x,colsT[x]));profiles[1].append((x,colsB[x]))}
                for y in (t+trimY)..<(b+1-trimY) where rowsR[y] >= 0 {profiles[2].append((rowsL[y],y));profiles[3].append((rowsR[y],y))}
                let cuts=[t==0,b==h-1,l==0,r==w-1], directions=[(0,-1),(0,1),(-1,0),(1,0)]
                // Unlike an externally clipped crop we own primary context: an
                // open top indicates the parent board. An open bottom can
                // hide another clause, so partial plates also abstain.
                if cuts.contains(true), start + Int(Double(t+b+1) * factor / 2) > half { unsafePanel = true }
                guard !cuts[0], !cuts[1], cuts.filter({$0}).count <= 1 else {continue}
                var frameOK=true
                for side in 0..<4 {
                    var observed=0, hits=0
                    for (x,y) in profiles[side] {
                        let (dx,dy)=directions[side]
                        let values=(1...(2*margin)).compactMap { distance -> Double? in
                            let xx=x+dx*distance,yy=y+dy*distance
                            return xx>=0 && xx<w && yy>=0 && yy<h ? luminance[yy*w+xx] : nil
                        }
                        guard values.count >= 4 else {continue}
                        observed += 1;let probe=min(margin,values.count/2),inner=Array(values.prefix(probe)),ink=inner.min()!
                        let offset=inner.firstIndex(of:ink)!,outside=Array(values.dropFirst(max(probe,offset+1)))
                        if ink <= paper*0.78 && !outside.isEmpty && outside.reduce(0,+)/Double(outside.count)-ink >= 5 {hits += 1}
                    }
                    let unseen=Double(observed)<0.5*Double(profiles[side].count)
                    if !(cuts[side] && unseen) && Double(hits)/Double(max(1,observed)) < 0.45 {frameOK=false;break}
                }
                guard frameOK else {continue}
                var inkCount=0
                if b-1 > t+2 && r-1 > l+2 {for y in (t+2)..<(b-1) {for x in (l+2)..<(r-1) {if luminance[y*w+x] < paper*0.7 {inkCount += 1}}}}
                let ink=Double(inkCount)/Double(max(1,(cw-4)*(ch-4)))
                // Keep a framed blank/washed-out panel: no text is not absence.
                allPanelsReadable = allPanelsReadable && (0.004...0.35).contains(ink)
                candidates.append([max(0,l-margin),max(0,t-margin),min(w,r+margin+1),min(h,b+margin+1)])
                panelBounds.append([l,t,r+1,b+1])
                bordersComplete = bordersComplete && !cuts.contains(true)
            }
            guard !candidates.isEmpty, candidates.count <= 3 else {continue}
            candidates.sort {$0[1]<$1[1]};var aligned=true
            if candidates.count>1 {for i in 1..<candidates.count {
                let a=candidates[i-1],b=candidates[i],aw=a[2]-a[0],bw=b[2]-b[0],gap=b[1]-a[3]
                if Double(min(aw,bw))<0.7*Double(max(aw,bw)) || Double(min(a[2],b[2])-max(a[0],b[0]))<0.8*Double(min(aw,bw)) || gap<0 || Double(gap)>0.15*Double(min(aw,bw)) {aligned=false}
            }}
            guard aligned else {continue}
            let x=Int(floor(Double(candidates.map{$0[0]}.min()!)*Double(width)/Double(w)))
            let top=start+Int(floor(Double(candidates.map{$0[1]}.min()!)*Double(nativeHeight)/Double(h)))
            let right=min(width,Int(ceil(Double(candidates.map{$0[2]}.max()!)*Double(width)/Double(w))))
            let bottom=min(height,start+Int(ceil(Double(candidates.map{$0[3]}.max()!)*Double(nativeHeight)/Double(h))))
            let y=max(half,top)
            if right-x>=48 && bottom-y>=32 && (top+bottom)/2>half {
                let components = panelBounds.sorted { $0[1] < $1[1] }.map { c -> TrafficSignPlateRect in
                    let cx = Int(floor(Double(c[0]) * Double(width) / Double(w)))
                    let cy = start + Int(floor(Double(c[1]) * Double(nativeHeight) / Double(h)))
                    let cr = min(width, Int(ceil(Double(c[2]) * Double(width) / Double(w))))
                    let cb = min(height, start + Int(ceil(Double(c[3]) * Double(nativeHeight) / Double(h))))
                    return .init(x: cx, y: cy, width: cr-cx, height: cb-cy)
                }
                let complete = bordersComplete && allPanelsReadable && !unsafePanel && components.allSatisfy {
                    $0.width >= 48 && $0.height >= 32 && $0.x >= 2 && $0.y >= half && $0.x + $0.width <= width - 2 && $0.y + $0.height <= height - 2
                }
                return .init(status: complete ? .complete : .unresolved,
                    union: .init(x:x,y:y,width:right-x,height:bottom-y), components: components,
                    decision: complete ? "all_framed_panels" : "clipped_or_parent_overlap")
            }
        }
        return nil
    }

    static func isPrimaryGraphic(width:Int,height:Int,rgba:[UInt8]) -> Bool {
        guard width>0,height>0,rgba.count==width*height*4 else {return true}
        var count=0,left=width,right=0,top=height
        for y in 0..<height {for x in 0..<width {let i=(y*width+x)*4,r=Int(rgba[i]),g=Int(rgba[i+1]),b=Int(rgba[i+2])
            if r>=80 && Double(r)>1.25*Double(g) && Double(r)>1.25*Double(b) {count += 1;left=min(left,x);right=max(right,x);top=min(top,y)}
        }}
        return Double(count)>=0.04*Double(width*height) && Double(right-left)>=0.6*Double(width) && Double(top)<0.25*Double(height)
    }
    static func hasUncoveredInk(width: Int, height: Int, rgba: [UInt8], coveredRows: Set<Int>) -> Bool {
        guard width >= 48, height >= 32, rgba.count == width*height*4 else { return true }
        var levels = [Int](); levels.reserveCapacity(width*height)
        for i in stride(from: 0, to: rgba.count, by: 4) {
            let red = Int(rgba[i]), green = Int(rgba[i+1]), blue = Int(rgba[i+2])
            levels.append((red+green+blue)/3)
        }
        let paper = levels.sorted()[Int(Double(levels.count)*0.9)]
        guard !coveredRows.isEmpty else { return true }
        let left = width/10, right = width-width/10, trim = max(4, Int(Double(height)*0.15))
        guard height > trim * 2 else { return true }
        var run = 0
        for y in trim..<(height-trim) {
            let dark = (left..<right).filter { levels[y*width+$0] < max(45, Int(Double(paper)*0.55)) }.count
            // Full-width frame lines are not glyphs. An unexplained run of
            // interior ink above OR below recognized text is an unread clause.
            let unexplained = !coveredRows.contains(y) && Double(dark) >= Double(right-left)*0.05 && Double(dark) <= Double(right-left)*0.55
            run = unexplained ? run+1 : 0
            if run >= max(3, Int((Double(height)*0.03).rounded())) { return true }
        }
        return false
    }

}
