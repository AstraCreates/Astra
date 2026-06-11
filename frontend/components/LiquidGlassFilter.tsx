"use client";

export default function LiquidGlassFilter() {
  return (
    <svg
      width="0"
      height="0"
      aria-hidden="true"
      style={{ position: "absolute", overflow: "hidden" }}
    >
      <defs>
        <filter
          id="glass-distortion"
          x="-10%"
          y="-10%"
          width="120%"
          height="120%"
          filterUnits="objectBoundingBox"
        >
          {/* Organic noise map */}
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.003 0.007"
            numOctaves="1"
            seed="17"
            result="turbulence"
          />
          {/* Sharpen noise into ridge-like bumps for specular */}
          <feComponentTransfer in="turbulence" result="mapped">
            <feFuncR type="gamma" amplitude="1" exponent="10" offset="0.5" />
            <feFuncG type="gamma" amplitude="0" exponent="1" offset="0" />
            <feFuncB type="gamma" amplitude="0" exponent="1" offset="0.5" />
          </feComponentTransfer>
          <feGaussianBlur in="turbulence" stdDeviation="3" result="softMap" />
          {/* Compute specular highlights off the bump map */}
          <feSpecularLighting
            in="softMap"
            surfaceScale="5"
            specularConstant="1"
            specularExponent="100"
            lightingColor="white"
            result="specLight"
          >
            <fePointLight x="-200" y="-200" z="300" />
          </feSpecularLighting>
          {/* Clip specular to source shape, then screen it over source */}
          <feComposite
            in="specLight"
            in2="SourceGraphic"
            operator="in"
            result="litImage"
          />
          <feComposite
            in="SourceGraphic"
            in2="litImage"
            operator="arithmetic"
            k1="0"
            k2="1"
            k3="0.28"
            k4="0"
            result="combined"
          />
          {/* Lenticular displacement — subtle warp */}
          <feDisplacementMap
            in="combined"
            in2="softMap"
            scale="38"
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
      </defs>
    </svg>
  );
}
