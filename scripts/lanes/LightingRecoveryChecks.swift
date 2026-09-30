import Foundation

@main struct LightingRecoveryChecks {
    static func main() {
        let w=384, h=216, x=190, y=170
        func image(_ background: UInt8, _ stripe: UInt8?, missingRight: Bool = false) -> [UInt8] {
            var gray=[UInt8](repeating:background,count:w*h)
            if let stripe {
                for yy in 0..<h { for xx in (x-2)...(missingRight ? w-1 : x+2) { gray[yy*w+xx]=stripe } }
            }
            return gray
        }
        func score(_ gray: [UInt8], _ mode: String, _ budget: Int = 10000) -> (Double,Bool) {
            LightingRecovery.mode=mode
            var used=0
            return LightingRecovery.response(gray,w,h,LightingRecovery.Row(gray,w,y),x,y,[1,2,3],{ cost in
                used += cost; return used <= budget
            })
        }
        for mode in ["A","B","AB"] {
            precondition(score(image(40,80),mode).0 >= 26,"dim measured stripe must be admitted")
            precondition(score(image(40,nil),mode).0 == 0,"flat dark road must abstain")
            precondition(score(image(40,80,missingRight:true),mode).0 == 0,"one border must abstain")
            precondition(score(image(10,20),mode).0 == 0,"noise floor must hold")
            precondition(score(image(40,255),mode).0 == 0,"clipped support must abstain")
            precondition(score(image(40,80),mode,0).1,"budget exhaustion must propagate")
        }
        precondition(score(image(40,60),"A").0 == 0,"A cannot normalize low contrast")
        precondition(score(image(40,60),"B").0 >= 26,"B can recover qualified relative contrast")
        var divergent=image(40,nil)
        for yy in 0..<h {
            let half = yy < y ? 1 : (yy > y ? 5 : 2)
            for xx in (x-half)...(x+half) { divergent[yy*w+xx]=90 }
        }
        precondition(score(divergent,"AB").0 == 0,"diverging borders must fail geometry")
        print("21 offline lighting assertions passed")
    }
}
