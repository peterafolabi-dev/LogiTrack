import React from "react";
import { createRoot } from "react-dom/client";
import { LazyMotion, domAnimation, m, useReducedMotion } from "framer-motion";

function AnimatedNumber({ element }) {
  const reduceMotion = useReducedMotion();
  const value = Number(element.dataset.value || 0);
  const decimals = Number(element.dataset.decimals || 0);
  const suffix = element.dataset.suffix || "";
  const prefix = element.dataset.prefix || "";
  const number = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
  const text = `${prefix}${number}${suffix}`;

  if (reduceMotion) return <span>{text}</span>;

  return (
    <LazyMotion features={domAnimation}>
    <m.span
      aria-label={text}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, amount: 0.7 }}
      variants={{
        hidden: {},
        visible: { transition: { delayChildren: 0.06, staggerChildren: 0.045 } },
      }}
      style={{ display: "inline-flex", whiteSpace: "pre" }}
    >
      {[...text].map((character, index) => (
        <m.span
          key={`${character}-${index}`}
          aria-hidden="true"
          variants={{
            hidden: { opacity: 0, y: 5 },
            visible: { opacity: 1, y: 0, transition: { duration: 0.22, ease: [0.16, 1, 0.3, 1] } },
          }}
          style={{ display: "inline-block" }}
        >
          {character}
        </m.span>
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
