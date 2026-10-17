import React from "react";
import { createRoot } from "react-dom/client";
import { LazyMotion, domAnimation, m, useReducedMotion, useScroll, useSpring, useTransform } from "framer-motion";

function ScrollCharacter({ character, index, count, progress }) {
  const start = 0.04 + (index / count) * 0.78;
  const end = Math.min(start + 0.2, 1);
  const opacity = useTransform(progress, [start, end], [0, 1]);
  const y = useTransform(progress, [start, end], [7, 0]);

  return (
    <m.span aria-hidden="true" style={{ display: "inline-block", opacity, y }}>
      {character}
    </m.span>
  );
}

function AnimatedNumber({ element }) {
  const ref = React.useRef(null);
  const reduceMotion = useReducedMotion();
  const value = Number(element.dataset.value || 0);
  const decimals = Number(element.dataset.decimals || 0);
  const suffix = element.dataset.suffix || "";
  const prefix = element.dataset.prefix || "";
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start 0.92", "end 0.42"],
  });
  const progress = useSpring(scrollYProgress, { stiffness: 150, damping: 34, mass: 0.25 });
  const number = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
  const text = `${prefix}${number}${suffix}`;

  if (reduceMotion) return <span>{text}</span>;

  return (
    <LazyMotion features={domAnimation}>
    <m.span
      ref={ref}
      aria-label={text}
      style={{ display: "inline-flex", whiteSpace: "pre" }}
    >
      {[...text].map((character, index) => (
        <ScrollCharacter key={`${character}-${index}`} character={character} index={index} count={text.length} progress={progress} />
      ))}
    </m.span>
    </LazyMotion>
  );
}

function mountLandingNumbers() {
  document.querySelectorAll("[data-motion-stat]").forEach((element) => {
    const className = element.className;
    createRoot(element).render(<AnimatedNumber element={element} />);
    element.className = className;
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountLandingNumbers, { once: true });
} else {
  mountLandingNumbers();
}
